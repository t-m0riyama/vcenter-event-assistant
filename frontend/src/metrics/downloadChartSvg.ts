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

function serializeMainSurfaceOnly(container: HTMLElement): string {
  const svg = findChartSvgForExport(container)
  if (!svg) {
    throw new Error('グラフの SVG が見つかりません')
  }
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

/**
 * One SVG: translated main chart surface + optional legend as XHTML in `foreignObject`.
 */
export function serializeRechartsWrapperWithLegend(wrapper: HTMLElement): string {
  const mainSvg = findChartSvgForExport(wrapper)
  if (!mainSvg) {
    throw new Error('グラフの SVG が見つかりません')
  }
  const legendEl = wrapper.querySelector('.recharts-legend-wrapper') as HTMLElement | null

  const wrapRect = wrapper.getBoundingClientRect()
  const w = Math.max(1, Math.round(wrapRect.width))
  const h = Math.max(1, Math.round(wrapRect.height))

  const mainRect = mainSvg.getBoundingClientRect()
  const tx = Math.round(mainRect.left - wrapRect.left)
  const ty = Math.round(mainRect.top - wrapRect.top)

  const outer = document.createElementNS(SVG_NS, 'svg')
  outer.setAttribute('xmlns', SVG_NS)
  outer.setAttribute('width', String(w))
  outer.setAttribute('height', String(h))
  outer.setAttribute('viewBox', `0 0 ${w} ${h}`)

  const g = document.createElementNS(SVG_NS, 'g')
  g.setAttribute('transform', `translate(${tx}, ${ty})`)
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
    fo.setAttribute('y', String(ly))
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

export function serializeChartSvg(container: HTMLElement): string {
  const wrapper = findRechartsWrapper(container)
  if (wrapper) {
    return serializeRechartsWrapperWithLegend(wrapper)
  }
  return serializeMainSurfaceOnly(container)
}

export function downloadChartSvg(container: HTMLElement | null, filename: string): void {
  if (!container) {
    throw new Error('グラフ領域がありません')
  }
  const xml = serializeChartSvg(container)
  const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
  triggerDownload(blob, filename)
}
