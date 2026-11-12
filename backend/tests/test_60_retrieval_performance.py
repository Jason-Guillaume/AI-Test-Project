"""可重复的 PostgreSQL 大知识库候选检索性能与索引验收。"""

import hashlib
import os

from sqlalchemy import text

from app.core.models.identity import User
from app.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, KnowledgeVersion
from app.knowledge.service import freeze, search
from tests.conftest import unique


def test_large_knowledge_search_is_bounded_and_uses_postgres_candidate_filter(api, admin, db):
    project_response = api.post(
        "/projects", username=admin, json={"name": unique("retrieval-performance")},
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    actor = db.query(User).filter_by(username=admin).one()

    base = KnowledgeBase(project_id=project_id, name="performance corpus")
    db.add(base)
    db.flush()
    document = KnowledgeDocument(project_id=project_id, base_id=base.id, name="corpus.md")
    db.add(document)
    db.flush()
    content = b"synthetic test corpus"
    version = KnowledgeVersion(
        document_id=document.id, version=1, digest=hashlib.sha256(content).hexdigest(),
        filename="corpus.md", content=content, status="READY",
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    db.add_all([
        KnowledgeChunk(
            version_id=version.id,
            position=index,
            text=(f"支付退款处理规范 needle42 命中案例 {index}" if index % 33 == 0
                  else f"项目说明和无关参考内容，编号 {index}。"),
        )
        for index in range(10000)
    ])
    db.commit()
    db.execute(text("ANALYZE knowledge_chunk"))
    snapshot = freeze(db, project_id, 0, actor)

    results, metadata = search(
        db, snapshot, actor, "支付退款 needle42", limit=8, candidate_limit=200,
        return_metadata=True,
    )
    assert results
    assert metadata["candidate_count"] == 200
    assert metadata["candidate_truncated"] is True
    assert metadata["duration_ms"] < 2000

    trigram_installed = bool(db.execute(text(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_trgm')",
    )).scalar())
    if trigram_installed:
        index = db.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE indexname='ix_knowledge_chunk_text_trgm'",
        )).scalar()
        assert index and "using gin" in index.lower()
        # 对小型隔离样本，成本模型可能选择顺序扫描；关闭它只用于验证可用的 GIN 路径。
        db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = db.execute(text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT id FROM knowledge_chunk WHERE text ILIKE '%needle42%' LIMIT 201
        """)).scalars().all()
        plan_text = "\n".join(plan)
        assert "ix_knowledge_chunk_text_trgm" in plan_text
        if os.environ.get("RAG_PERF_REPORT") == "1":
            print(f"RAG_PERF duration_ms={metadata['duration_ms']} candidates={metadata['candidate_count']} "
                  f"truncated={metadata['candidate_truncated']}\n{plan_text}")
