import type { IncidentLinkResult } from '../../api/schemas/incidents'

const resultMessages: Record<IncidentLinkResult['result'], string> = {
  added: '件を追加しました',
  already_linked: '件はすでに紐付いています',
  not_found: '件は見つかりませんでした',
  no_result: '件には保存した結果がありません',
  limit_exceeded: '件は紐付けの上限を超えています',
}

export function formatIncidentLinkResults(results: readonly IncidentLinkResult[]): string {
  const counts = new Map<IncidentLinkResult['result'], number>()
  for (const { result } of results) counts.set(result, (counts.get(result) ?? 0) + 1)
  return (Object.keys(resultMessages) as IncidentLinkResult['result'][])
    .filter((result) => counts.has(result))
    .map((result) => `${counts.get(result)} ${resultMessages[result]}`)
    .join('。') || '追加する項目はありませんでした'
}
