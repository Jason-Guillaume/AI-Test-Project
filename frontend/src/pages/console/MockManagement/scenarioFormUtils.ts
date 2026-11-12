export const JSON_RULE = {
  validator: (_: unknown, value: string | undefined) => {
    if (!value || !value.trim()) return Promise.resolve();
    try {
      JSON.parse(value);
      return Promise.resolve();
    } catch {
      return Promise.reject(new Error('不是合法 JSON'));
    }
  },
};

export const parseJson = (text: string | undefined, fallback: unknown) => {
  if (!text || !text.trim()) return fallback;
  return JSON.parse(text);
};
