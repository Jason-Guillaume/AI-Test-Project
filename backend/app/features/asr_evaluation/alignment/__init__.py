"""ASR 评测的有界纯文本对齐算法入口。"""

from app.features.asr_evaluation.alignment.align import align_triplet, edit_ratio

__all__ = ["align_triplet", "edit_ratio"]
