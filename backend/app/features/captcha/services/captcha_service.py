"""图形验证码核心服务：签发、渲染与校验。

存储策略（**关键**）：
- 进程内 dict + threading.Lock，一次性使用（校验即删除）
- 每次签发时机会式清理过期条目，不做后台定时任务
- **明确限制**：单进程部署。多 worker / 多实例部署不可用；
  需要分布式时必须切换到 Redis 或 DB 后端，本模块不做分布式一致性

字符集排除易混淆字符：0/O/1/I/l；长度与图片参数由 app.shared.config.settings 控制。
"""

from __future__ import annotations

import base64
import io
import random
import threading
import uuid
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

from app.shared.config import settings

# 排除易混淆字符：0/O 与 1/I/l。
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# 存储条目结构：code 与过期时间；challenge_id 直接作为 key。
# 类型为 dict[str, dict] 而非 NamedTuple：写入频率很低，可读性优先于严格类型。
_STORAGE: dict[str, dict] = {}
_LOCK = threading.Lock()


def _generate_code(length: int) -> str:
    """生成指定长度的随机校验码，字符取自 CODE_CHARS。"""
    return "".join(random.choice(CODE_CHARS) for _ in range(length))


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载系统 TTF 字体；找不到时回退 Pillow 默认位图字体，避免缺字体直接崩。

    优先顺序：macOS 系统字体 → Linux DejaVu → Pillow 默认。
    """
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except (OSError, IOError):
            # 字体缺失只记录到默认字体路径，不打印日志（避免污染正常请求日志）。
            continue
    return ImageFont.load_default()


def _render_image(code: str) -> str:
    """渲染验证码图片，返回 data:image/png;base64 完整 URI。

    视觉层次：浅底 → 干扰线 → 逐字独立旋转的字符层 → 噪声点。
    """
    width = settings.CAPTCHA_IMAGE_WIDTH
    height = settings.CAPTCHA_IMAGE_HEIGHT
    image = Image.new("RGB", (width, height), color=(245, 245, 245))
    draw = ImageDraw.Draw(image)

    # 干扰线：3-5 条随机直线，颜色偏中灰，降低 OCR 识别率而不完全盖住字符。
    for _ in range(random.randint(3, 5)):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        line_color = (
            random.randint(100, 200),
            random.randint(100, 200),
            random.randint(100, 200),
        )
        draw.line((x1, y1, x2, y2), fill=line_color, width=1)

    # 逐字绘制：每个字符独立画到透明子图，旋转后再拼贴，避免同一旋转角度导致字符形状一致。
    font = _load_font(height - 12)
    char_width = (width - 20) / max(len(code), 1)
    for index, char in enumerate(code):
        x = 8 + index * char_width
        y = random.randint(2, 8)
        char_color = (
            random.randint(30, 120),
            random.randint(30, 120),
            random.randint(30, 120),
        )
        char_layer = Image.new("RGBA", (28, 32), color=(0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_layer)
        char_draw.text((4, 0), char, font=font, fill=char_color)
        angle = random.randint(-25, 25)
        char_layer = char_layer.rotate(angle, resample=Image.BICUBIC, expand=True)
        image.paste(char_layer, (int(x), int(y)), char_layer)

    # 噪声点：随机散布深色点，进一步干扰 OCR。
    for _ in range(random.randint(30, 50)):
        px = random.randint(0, width - 1)
        py = random.randint(0, height - 1)
        gray = random.randint(50, 150)
        draw.point((px, py), fill=(gray, gray, gray))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _purge_expired_locked(now: datetime) -> None:
    """清掉所有已过期的 challenge；调用方必须已持有 _LOCK。"""
    expired = [cid for cid, entry in _STORAGE.items() if entry["expires_at"] <= now]
    for cid in expired:
        _STORAGE.pop(cid, None)


def generate_challenge() -> tuple[str, str, int]:
    """签发一次图形验证码。

    Returns:
        (challenge_id, image_data_uri, expires_in) 三元组。
        校验码本身不返回给调用方，只在内存存储中保留，供 verify_challenge 使用。
    """
    code = _generate_code(settings.CAPTCHA_LENGTH)
    image_uri = _render_image(code)
    challenge_id = uuid.uuid4().hex
    expires_at = datetime.now() + timedelta(seconds=settings.CAPTCHA_TTL_SECONDS)

    with _LOCK:
        # 机会式清理：写入前顺手清掉过期条目，避免长时间运行时字典无限膨胀。
        _purge_expired_locked(now=datetime.now())
        _STORAGE[challenge_id] = {"code": code, "expires_at": expires_at}

    return challenge_id, image_uri, int(settings.CAPTCHA_TTL_SECONDS)


def verify_challenge(challenge_id: str, code: str) -> bool:
    """校验验证码；通过则立即删除（一次性使用）。

    Args:
        challenge_id: 由 generate_challenge 返回的 ID。
        code: 用户输入的校验码。

    Returns:
        bool: 校验通过返回 True；其余情况（不存在、过期、不匹配、复用）统一返回 False，
        不区分失败原因，避免通过错误差异推断 challenge 是否曾被签发过。
    """
    if not challenge_id or not code:
        return False
    normalized = code.strip().upper()
    with _LOCK:
        # pop 前先取出再比较，保证「无论校验成败都删除」的一次性语义。
        entry = _STORAGE.pop(challenge_id, None)
        if entry is None:
            return False
        if entry["expires_at"] <= datetime.now():
            return False
        return entry["code"].upper() == normalized


def _reset_storage() -> None:
    """测试用：清空 challenge 存储。仅由测试调用，业务代码不应调用。"""
    with _LOCK:
        _STORAGE.clear()
