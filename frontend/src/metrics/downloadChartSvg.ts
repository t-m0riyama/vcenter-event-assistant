/**
 * Serialize the Recharts chart for download.
 * - Main plot: largest `svg.recharts-surface` (legend icons are smaller surfaces).
 * - Legend: HTML in `div.recharts-legend-wrapper` (sibling inside `.recharts-wrapper`), merged via `foreignObject`.
 */

const SVG_NS = 'http://www.w3.org/2000/svg'
const XHTML_NS = 'http://www.w3.org/1999/xhtml'

export function findRechartsWrapper(container: HTMLElement): HTMLElement | null {
  return container.querySelector('.recharts-wrapper')
}

/** Pixel area for choosing the main plot (legend icons also use `recharts-surface`). */
function svgPixelArea(svg: SVGSVGElement): number {
  const r = svg.getBoundingClientRect()
  let w = r.width
  let h = r.height
  if (w <= 0 || h <= 0) {
    const wa = svg.getAttribute('width')
    const ha = svg.getAttribute('height')
    w = wa && !wa.endsWith('%') ? parseFloat(wa) : 0
    h = ha && !ha.endsWith('%') ? parseFloat(ha) : 0
  }
  return w * h
}

/**
 * Main chart and each legend icon are both `svg.recharts-surface`; we need the largest one.
 */
export function findChartSvgForExport(container: HTMLElement): SVGSVGElement | null {
  const surfaces = Array.from(container.querySelectorAll('svg.recharts-surface')) as SVGSVGElement[]
  if (surfaces.length > 0) {
    let best: SVGSVGElement | null = null
    let bestArea = 0
    for (const s of surfaces) {
      const area = svgPixelArea(s)
      if (area > bestArea) {
        bestArea = area
        best = s
      }
    }
    if (best) return best
  }
  const svgs = Array.from(container.querySelectorAll('svg')) as SVGSVGElement[]
  if (svgs.length === 0) return null
  let best: SVGSVGElement | null = null
  let bestArea = 0
  for (const s of svgs) {
    const area = svgPixelArea(s)
    if (area > bestArea) {
      bestArea = area
      best = s
    }
  }
  return best
}

export function sanitizeFilenameSegment(segment: string): string {
  return segment
    .trim()
    .replace(/[/\\?%*:|"<>]/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 200)
}

export function formatMetricsDownloadTimestamp(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
}

/** Base filename without extension: `metrics-{vcenter|all}-{metricKey}-{YYYYMMDD-HHmmss}`. */
export function buildMetricsExportBasename(
  vcenterId: string,
  vcenterLabelWhenSelected: string,
  metricKey: string,
): string {
  const vcPart = !vcenterId.trim() ? 'all' : sanitizeFilenameSegment(vcenterLabelWhenSelected)
  const keyPart = sanitizeFilenameSegment(metricKey || 'metric')
  const ts = formatMetricsDownloadTimestamp(new Date())
  return `metrics-${vcPart}-${keyPart}-${ts}`
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  a.click()
  URL.revokeObjectURL(url)
}

/** グラフ SVG エクスポート時に上部へ描画するタイトル（中央揃え・複数行）。 */
export type ChartSvgExportTitle = {
  readonly lines: readonly string[]
}

const TITLE_FONT_SIZE = 14
const TITLE_LINE_HEIGHT = 1.35
const TITLE_LINE_GAP = 4
const TITLE_PAD_TOP = 8
const TITLE_PAD_BOTTOM = 8

function computeTitleBlockHeight(lines: readonly string[]): number {
  if (lines.length === 0) return 0
  return Math.ceil(
    TITLE_PAD_TOP +
      lines.length * TITLE_FONT_SIZE * TITLE_LINE_HEIGHT +
      (lines.length - 1) * TITLE_LINE_GAP +
      TITLE_PAD_BOTTOM,
  )
}

function createTitleTextElements(
  width: number,
  lines: readonly string[],
): SVGTextElement[] {
  const out: SVGTextElement[] = []
  let y = TITLE_PAD_TOP + TITLE_FONT_SIZE
  for (let i = 0; i < lines.length; i++) {
    const t = document.createElementNS(SVG_NS, 'text')
    t.setAttribute('x', String(width / 2))
    t.setAttribute('y', String(y))
    t.setAttribute('text-anchor', 'middle')
    t.setAttribute('font-family', 'system-ui, -apple-system, sans-serif')
    t.setAttribute('font-size', String(TITLE_FONT_SIZE))
    t.setAttribute('font-weight', '600')
    t.setAttribute('fill', '#1d1d1f')
    t.textContent = lines[i]
    out.push(t)
    if (i < lines.length - 1) {
      y += TITLE_FONT_SIZE * TITLE_LINE_HEIGHT + TITLE_LINE_GAP
    }
  }
  return out
}

function serializeMainSurfaceOnly(
  container: HTMLElement,
  title?: ChartSvgExportTitle,
): string {
  const svg = findChartSvgForExport(container)
  if (!svg) {
    throw new Error('グラフの SVG が見つかりません')
  }
  const titleH =
    title?.lines?.length && title.lines.length > 0
      ? computeTitleBlockHeight(title.lines)
      : 0

  if (titleH === 0) {
    const clone = svg.cloneNode(true) as SVGSVGElement
    if (!clone.getAttribute('xmlns')) {
      clone.setAttribute('xmlns', SVG_NS)
    }
    const r = svg.getBoundingClientRect()
    if (r.width > 0 && r.height > 0) {
      clone.setAttribute('width', String(Math.round(r.width)))
      clone.setAttribute('height', String(Math.round(r.height)))
    }
    return new XMLSerializer().serializeToString(clone)
  }

  const containerRect = container.getBoundingClientRect()
  const w = Math.max(1, Math.round(containerRect.width))
  const h = Math.max(1, Math.round(containerRect.height))
  const mainRect = svg.getBoundingClientRect()
  const tx = Math.round(mainRect.left - containerRect.left)
  const ty = Math.round(mainRect.top - containerRect.top)

  const outer = document.createElementNS(SVG_NS, 'svg')
  outer.setAttribute('xmlns', SVG_NS)
  outer.setAttribute('width', String(w))
  outer.setAttribute('height', String(h + titleH))
  outer.setAttribute('viewBox', `0 0 ${w} ${h + titleH}`)

  for (const el of createTitleTextElements(w, title!.lines)) {
    outer.appendChild(el)
  }

  const g = document.createElementNS(SVG_NS, 'g')
  g.setAttribute('transform', `translate(${tx}, ${ty + titleH})`)
  const mainClone = svg.cloneNode(true) as SVGSVGElement
  if (!mainClone.getAttribute('xmlns')) {
    mainClone.setAttribute('xmlns', SVG_NS)
  }
  if (mainRect.width > 0 && mainRect.height > 0) {
    mainClone.setAttribute('width', String(Math.round(mainRect.width)))
    mainClone.setAttribute('height', String(Math.round(mainRect.height)))
  }
  g.appendChild(mainClone)
  outer.appendChild(g)
  return new XMLSerializer().serializeToString(outer)
}

/**
 * One SVG: translated main chart surface + optional legend as XHTML in `foreignObject`.
 */
export function serializeRechartsWrapperWithLegend(
  wrapper: HTMLElement,
  title?: ChartSvgExportTitle,
): string {
  const mainSvg = findChartSvgForExport(wrapper)
  if (!mainSvg) {
    throw new Error('グラフの SVG が見つかりません')
  }
  const legendEl = wrapper.querySelector('.recharts-legend-wrapper') as HTMLElement | null

  const wrapRect = wrapper.getBoundingClientRect()
  const w = Math.max(1, Math.round(wrapRect.width))
  const h = Math.max(1, Math.round(wrapRect.height))

  const titleH =
    title?.lines?.length && title.lines.length > 0
      ? computeTitleBlockHeight(title.lines)
      : 0

  const mainRect = mainSvg.getBoundingClientRect()
  const tx = Math.round(mainRect.left - wrapRect.left)
  const ty = Math.round(mainRect.top - wrapRect.top)

  const outer = document.createElementNS(SVG_NS, 'svg')
  outer.setAttribute('xmlns', SVG_NS)
  outer.setAttribute('width', String(w))
  outer.setAttribute('height', String(h + titleH))
  outer.setAttribute('viewBox', `0 0 ${w} ${h + titleH}`)

  if (titleH > 0 && title?.lines?.length) {
    for (const el of createTitleTextElements(w, title.lines)) {
      outer.appendChild(el)
    }
  }

  const g = document.createElementNS(SVG_NS, 'g')
  g.setAttribute('transform', `translate(${tx}, ${ty + titleH})`)
  const mainClone = mainSvg.cloneNode(true) as SVGSVGElement
  if (!mainClone.getAttribute('xmlns')) {
    mainClone.setAttribute('xmlns', SVG_NS)
  }
  if (mainRect.width > 0 && mainRect.height > 0) {
    mainClone.setAttribute('width', String(Math.round(mainRect.width)))
    mainClone.setAttribute('height', String(Math.round(mainRect.height)))
  }
  g.appendChild(mainClone)
  outer.appendChild(g)

  if (legendEl) {
    const lr = legendEl.getBoundingClientRect()
    const lx = Math.round(lr.left - wrapRect.left)
    const ly = Math.round(lr.top - wrapRect.top)
    const lw = Math.max(1, Math.round(lr.width))
    const lh = Math.max(1, Math.round(lr.height))

    const fo = document.createElementNS(SVG_NS, 'foreignObject')
    fo.setAttribute('x', String(lx))
    fo.setAttribute('y', String(ly + titleH))
    fo.setAttribute('width', String(lw))
    fo.setAttribute('height', String(lh))

    const div = legendEl.cloneNode(true) as HTMLElement
    div.setAttribute('xmlns', XHTML_NS)
    div.style.position = 'relative'
    div.style.left = ''
    div.style.right = ''
    div.style.top = ''
    div.style.bottom = ''
    div.style.margin = '0'
    fo.appendChild(div)
    outer.appendChild(fo)
  }

  return new XMLSerializer().serializeToString(outer)
}

export function serializeChartSvg(
  container: HTMLElement,
  title?: ChartSvgExportTitle,
): string {
  const wrapper = findRechartsWrapper(container)
  if (wrapper) {
    return serializeRechartsWrapperWithLegend(wrapper, title)
  }
  return serializeMainSurfaceOnly(container, title)
}

/**
 * グラフ SVG をダウンロードする。`title` を渡すと最上部に中央揃えの `<text>` を追加する。
 */
export function downloadChartSvg(
  container: HTMLElement | null,
  filename: string,
  title?: ChartSvgExportTitle,
): void {
  if (!container) {
    throw new Error('グラフ領域がありません')
  }
  const xml = serializeChartSvg(container, title)
  const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
  triggerDownload(blob, filename)
}
