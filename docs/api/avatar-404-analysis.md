# Get Avatar URL 404 问题分析

## 一、接口逻辑流程（方案 B：文件系统）

```
GET /profile/avatar?size={origin|64x64|256x256}
Header: Authorization: Bearer <refresh_token>
```

### 执行顺序

1. **参数校验**：`size` 必填且为 `origin`、`64x64`、`256x256` 之一  
   - 失败 → **400** "Invalid or missing size parameter"

2. **认证**：从 `Authorization` 解析 refresh token，查 Redis/DB  
   - 失败 → **401** "Invalid or expired token"

3. **文件映射**：`size` → 文件名  
   - `origin` → `original.webp`  
   - `64x64` → `64.webp`  
   - `256x256` → `256.webp`

4. **检查文件**：`uploads/avatars/{user_id}/{filename}` 是否存在  
   - 不存在 → **404** "User has no avatar"

5. 成功 → **200** `{ "url": "/uploads/avatars/1/original.webp" }`

**注意**：不再使用数据库，以磁盘文件为准。

---

## 二、404 来源

| 来源 | 条件 | 响应 body |
|------|------|-----------|
| **文件不存在** | `uploads/avatars/{user_id}/{filename}` 不存在 | `{"message": "User has no avatar"}` |

---

## 三、404 可能原因（Apifox 正常、前端异常）

### 1. 不同用户（不同 token）

- Apifox：用户 A 的 token，已上传头像  
- 前端：用户 B 的 token，未上传头像  

**排查**：前端用与 Apifox 相同的 token 调用，看是否仍 404。

### 2. 请求的 size 文件不存在

- 上传的是小图（如 32×32），可能只生成 `original.webp`（无 `64.webp`、`256.webp`）
- 请求 `size=256x256` 时，`256.webp` 不存在 → 404

**排查**：前端用 `size=origin` 测试（`original.webp` 每次上传都会生成）。

### 3. 前端未传 refresh token

- 若传了 access token 或错误 token，会返回 **401**，不是 404  
- 若返回 404，说明认证已通过，请求已到达接口逻辑

### 4. 路径错误（路由 404）

- 正确：`GET /profile/avatar?size=origin`  
- 若前端 baseURL 为 `https://xxx/api`，请求 `/profile/avatar`，实际会变成：  
  `https://xxx/api/profile/avatar`  
- 后端未挂载 `/api` 前缀，该路由不存在 → 404

**排查**：前端实际请求 URL 应为 `{baseURL}/profile/avatar?size=origin`，不要多加 `/api`。

### 5. 头像文件未上传或已删除

- 方案 B 以磁盘为准，不查数据库  
- 若用户从未上传头像，或头像目录被手动删除，对应文件不存在 → 404

**排查**：确认 `uploads/avatars/{user_id}/` 下是否有对应文件。

### 6. 请求的是头像文件 URL，不是接口

- 接口：`GET /profile/avatar?size=origin` → 返回 `{ "url": "/uploads/avatars/1/original.webp" }`  
- 实际图片：`GET /uploads/avatars/1/original.webp`  
- 若前端直接请求 `/uploads/avatars/1/original.jpg`，而文件不存在或路径错误，会由 StaticFiles 返回 404

**排查**：确认前端是请求 `/profile/avatar` 接口，还是直接请求图片 URL。

---

## 四、建议排查步骤

1. **看 404 响应 body**  
   - `{"message": "User has no avatar"}` → 对应文件不存在  
   - 其他或无 body → 可能是路由或代理 404

2. **检查请求 URL**  
   - 应为 `GET {baseURL}/profile/avatar?size=origin`  
   - 确认 baseURL 是否带 `/api`  
   - 确认 `size` 参数是否正确拼写（`origin`、`64x64`、`256x256`）

3. **检查 token**  
   - 使用 refresh token，不是 access token  
   - Header：`Authorization: Bearer <refresh_token>`

4. **用 Apifox 的请求复现**  
   - 前端复制 Apifox 的完整 URL、Headers、Query 发请求，看是否仍 404。

### 后端日志

`get_avatar` 在 404 时会输出：`get_avatar 404: user_id=X size=Y file=Z not found on disk`

---

## 五、路由与路径确认

| 路由 | 完整路径 | 说明 |
|------|----------|------|
| 获取头像 URL | `GET /profile/avatar?size=origin` | profile 无 `/api` 前缀 |
| 上传头像 | `PUT /profile/avatar` | 同上 |
| 删除头像 | `DELETE /profile/avatar` | 同上 |
| 静态文件 | `GET /uploads/avatars/{user_id}/{filename}` | 实际图片 URL |

**注意**：Admin 路由前缀为 `/api/admin`，profile 路由无 `/api` 前缀。
