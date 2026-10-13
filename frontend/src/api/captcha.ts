// 图形验证码相关接口。后端由 GET /captcha 签发，注册请求体携带 challenge_id + captcha_code。
// 图片以 base64 data URI 返回，前端直接绑到 <img> 的 src；点击图片刷新即重发请求。
import { api } from './client';

/** 图形验证码签发响应体。 */
export interface CaptchaResponse {
  challenge_id: string; // 校验时回传给后端，用于取出真实验证码
  image_base64: string; // data:image/png;base64,... 可直接作为 <img src>
  expires_in: number; // 有效期秒数；到期后 verify 一定失败
}

/** 验证码接口集合。 */
export const captchaApi = {
  /** 签发一张新的验证码图片。 */
  issue: () => api.get<CaptchaResponse>('/captcha'),
};
