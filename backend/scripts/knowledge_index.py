"""Operator-only backfill/retry of an existing knowledge index generation.

Run from backend: python -m scripts.knowledge_index backfill --generation-id ID
"""
import argparse

from app.core.database.session import SessionLocal
from app.knowledge.indexing import backfill_generation, lock_project
from app.knowledge.models import KnowledgeIndexGeneration, KnowledgeIndexJob


def main():
    parser = argparse.ArgumentParser(description='Knowledge index maintenance')
    parser.add_argument('action', choices=('backfill', 'retry', 'status'))
    parser.add_argument('--generation-id', type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        generation = db.get(KnowledgeIndexGeneration, args.generation_id)
        if generation is None:
            parser.error('generation not found')
        if args.action == 'backfill':
            count = backfill_generation(db, generation.id)
            db.commit()
            print(f'queued={count}')
        elif args.action == 'retry':
            lock_project(db, generation.project_id)
            if generation.state not in {'BUILDING', 'ACTIVE', 'STANDBY'}:
                parser.error('generation cannot be retried')
            rows = db.query(KnowledgeIndexJob).filter_by(generation_id=generation.id, status='FAILED').all()
            for row in rows:
                row.status, row.attempts, row.error, row.next_attempt_at = 'QUEUED', 0, None, None
            db.commit()
            print(f'queued={len(rows)}')
        else:
            from sqlalchemy import func
            counts = db.query(KnowledgeIndexJob.status, func.count(KnowledgeIndexJob.id)).filter_by(
                generation_id=generation.id).group_by(KnowledgeIndexJob.status).all()
            print(f'generation={generation.id} state={generation.state} jobs={dict(counts)}')


if __name__ == '__main__':
    main()
