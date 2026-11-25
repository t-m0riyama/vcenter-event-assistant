import { z } from 'zod'

export const diagnosticProductSchema = z.enum(['esxi', 'vcenter'])

const settingMetaSchema = z.object({
  id: z.string(),
  revision: z.string(),
  created_by: z.string(),
  updated_by: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
})

const diagnosticTargetInputSchema = z.object({
  product: diagnosticProductSchema,
  vcenter_id: z.string(),
  host_moid: z.string().nullable(),
  host_name: z.string(),
  ssh_connection_id: z.string(),
})

export const diagnosticTargetSchema = diagnosticTargetInputSchema.extend(settingMetaSchema.shape)
export const diagnosticTargetsSchema = z.array(diagnosticTargetSchema)
export const diagnosticHostsSchema = z.array(z.object({
  id: z.string(),
  name: z.string(),
  host: z.string(),
}))

const diagnosticCommandInputSchema = z.object({
  product: diagnosticProductSchema,
  title: z.string(),
  description: z.string(),
  template: z.string(),
  param_definitions: z.array(z.object({ name: z.string(), type: z.string() })),
})

export const diagnosticBuiltinCommandSchema = diagnosticCommandInputSchema.extend({ id: z.string() })
export const diagnosticCommandSchema = diagnosticCommandInputSchema.extend(settingMetaSchema.shape)
export const diagnosticCatalogSchema = z.object({
  builtin: diagnosticBuiltinCommandSchema.array(),
  custom: z.array(diagnosticCommandSchema),
  parameter_types: z.array(z.string()),
})

export const diagnosticTemplateErrorSchema = z.object({
  reason: z.enum([
    'control_character',
    'undefined_parameter',
    'unused_parameter',
    'dollar_prefix',
    'backslash_prefix',
    'invalid_parameter_name',
    'duplicate_parameter',
    'unknown_parameter_type',
    'too_many_parameters',
  ]),
  parameter: z.string().nullable(),
})

export type DiagnosticProduct = z.infer<typeof diagnosticProductSchema>
export type DiagnosticTarget = z.infer<typeof diagnosticTargetSchema>
export type DiagnosticTargetInput = z.infer<typeof diagnosticTargetInputSchema>
export type DiagnosticHost = z.infer<typeof diagnosticHostsSchema>[number]
export type DiagnosticCommand = z.infer<typeof diagnosticCommandSchema>
export type DiagnosticCommandInput = z.infer<typeof diagnosticCommandInputSchema>

export const diagnosticProcedureSchema = z.object({
  pattern_id: z.string(),
  title: z.string(),
  steps: z.array(z.object({
    text: z.string(),
    commands: z.array(z.object({ id: z.string(), title: z.string() })),
  })),
})

export const diagnosticCandidateSchema = z.object({
  procedure: diagnosticProcedureSchema,
  reasons: z.array(z.object({ kind: z.enum(['alert', 'event']), link_id: z.number().int() })),
  target: z.object({ id: z.string(), host_name: z.string() }).nullable(),
})

export const diagnosticPreviewSchema = z.object({
  command_line: z.string(),
  host_name: z.string(),
  ssh_host: z.string(),
  ssh_port: z.number().int(),
  ssh_username: z.string(),
  fingerprint: z.string().min(1),
})

export const diagnosticRunSchema = z.object({
  id: z.number().int(),
  incident_id: z.string(),
  command_kind: z.enum(['builtin', 'custom']),
  command_ref: z.string(),
  command_title: z.string(),
  command_line: z.string(),
  executed: z.boolean().nullable(),
  params: z.record(z.string(), z.string()),
  target_id: z.string().nullable(),
  product: diagnosticProductSchema,
  host_name: z.string(),
  ssh_host: z.string(),
  ssh_port: z.number().int(),
  ssh_username: z.string(),
  status: z.enum(['succeeded', 'failed', 'error']),
  exit_status: z.number().int().nullable(),
  error_code: z.string().nullable(),
  stdout_truncated: z.boolean(),
  stderr_truncated: z.boolean(),
  elapsed_ms: z.number().int(),
  started_at: z.iso.datetime({ offset: true, local: true }),
  finished_at: z.iso.datetime({ offset: true, local: true }),
  run_by: z.string(),
})

export const diagnosticOutputSchema = diagnosticRunSchema.extend({ stdout: z.string(), stderr: z.string() })
export const diagnosticParameterErrorsSchema = z.array(z.object({
  parameter: z.string(),
  reason: z.enum(['missing', 'unknown', 'invalid_value']),
}))

export type DiagnosticProcedure = z.infer<typeof diagnosticProcedureSchema>
export type DiagnosticCandidate = z.infer<typeof diagnosticCandidateSchema>
export type DiagnosticRun = z.infer<typeof diagnosticRunSchema>
export type DiagnosticOutput = z.infer<typeof diagnosticOutputSchema>
export type DiagnosticPreview = z.infer<typeof diagnosticPreviewSchema>
export type DiagnosticCommandRef = { builtin: string } | { custom: string }
export type DiagnosticPreviewInput = { target_id: string; command: DiagnosticCommandRef; params: Record<string, string> }
