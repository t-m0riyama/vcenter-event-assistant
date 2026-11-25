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

export const diagnosticCommandSchema = diagnosticCommandInputSchema.extend(settingMetaSchema.shape)
export const diagnosticCatalogSchema = z.object({
  builtin: z.array(diagnosticCommandInputSchema.extend({ id: z.string() })),
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
