/** 模板页共用的轻量 JSON 请求器（鉴权走统一传输层）。 */
import { createJsonRequester } from '../../api/client'

export const request = createJsonRequester()
