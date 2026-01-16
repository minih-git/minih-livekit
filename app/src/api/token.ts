/**
 * Token API 模块
 * 负责从 Agent 服务器获取 LiveKit 房间 Token
 */

// Token 服务器地址（开发环境）
// Token 服务器地址（开发环境）
// 优先使用 window.__ENV__ 中的配置，即使是空字符串（表示使用相对路径）
const TOKEN_SERVER_URL = ".";

/**
 * Token 响应接口
 */
interface TokenResponse {
  token: string;
}

/**
 * 错误响应接口
 */
interface ErrorResponse {
  error: string;
}

/**
 * 从 Token 服务器获取 LiveKit 房间 Token
 *
 * @param roomName - 房间名称
 * @param participantName - 参与者名称
 * @returns LiveKit Token 字符串
 * @throws Error 如果请求失败
 */
export async function fetchToken(
  roomName: string,
  participantName: string
): Promise<string> {
  const response = await fetch(`${TOKEN_SERVER_URL}/api/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      roomName,
      participantName,
    }),
  });

  if (!response.ok) {
    const errorData: ErrorResponse = await response.json();
    throw new Error(errorData.error || `HTTP error: ${response.status}`);
  }

  const data: TokenResponse = await response.json();
  return data.token;
}

/**
 * 生成随机参与者 ID
 *
 * @param prefix - ID 前缀
 * @returns 格式为 "prefix-xxxx" 的随机 ID
 */
export function generateParticipantId(prefix: string = "user"): string {
  const randomPart = Math.random().toString(36).substring(2, 6);
  return `${prefix}-${randomPart}`;
}
