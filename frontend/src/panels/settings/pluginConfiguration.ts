export type ConfigurationSchema = {
  type: string; title?: string; description?: string; default?: unknown; enum?: unknown[]
  properties?: Record<string, ConfigurationSchema>; items?: ConfigurationSchema
  minimum?: number; maximum?: number; minLength?: number; maxLength?: number; maxItems?: number
  minItems?: number; required?: string[]
  'x-vea-widget'?: string; 'x-vea-generated-id'?: boolean; 'x-vea-vcenter-field'?: string; 'x-vea-host-field'?: string
}

export function initialValue(schema: ConfigurationSchema): unknown {
  if (schema['x-vea-generated-id']) return typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('')
  if (schema.default !== undefined) return schema.default
  if (schema.type === 'object') return Object.fromEntries(Object.entries(schema.properties ?? {}).map(([k, s]) => [k, initialValue(s)]))
  if (schema.type === 'array') return []
  if (schema.type === 'boolean') return false
  if (schema.type === 'number' || schema.type === 'integer') return schema.minimum ?? 0
  return ''
}
