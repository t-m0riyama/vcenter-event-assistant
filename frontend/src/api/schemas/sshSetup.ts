import { z } from 'zod'

// OpenSSH 形式は鍵の種類、Base64 のデータ、任意のコメントが 1 行に並ぶ。
export const sshPublicKeySchema = z.string().regex(/^[\w@.+-]+ [A-Za-z0-9+/]+={0,2}(?: [^\r\n]*)?\r?\n?$/)

export const sshCredentialSchema = z.object({
  id: z.string(),
  name: z.string(),
  public_key: sshPublicKeySchema,
})

export const sshConnectionSchema = z.object({
  id: z.string(),
  name: z.string(),
  host: z.string(),
  port: z.number().int(),
  username: z.string(),
  credential_id: z.string(),
  revision: z.number().int(),
  approved: z.boolean(),
  fingerprint: z.string().nullable(),
  candidate_fingerprint: z.string().nullable(),
})

export const sshCredentialsSchema = z.array(sshCredentialSchema)
export const sshConnectionsSchema = z.array(sshConnectionSchema)
export type SSHCredential = z.infer<typeof sshCredentialSchema>
export type SSHConnection = z.infer<typeof sshConnectionSchema>
