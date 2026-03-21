import { describe, expect, it } from 'vitest'

import { findChartSvgForExport, serializeRechartsWrapperWithLegend } from './downloadChartSvg'

const SVG_NS = 'http://www.w3.org/2000/svg'

describe('findChartSvgForExport', () => {
  it('prefers svg.recharts-surface over an earlier smaller svg', () => {
    const container = document.createElement('div')
    const legend = document.createElement('svg')
    legend.setAttribute('width', '16')
    legend.setAttribute('height', '16')
    const surface = document.createElement('svg')
    surface.setAttribute('class', 'recharts-surface')
    surface.setAttribute('width', '400')
    surface.setAttribute('height', '320')
    container.appendChild(legend)
    container.appendChild(surface)
    expect(findChartSvgForExport(container)).toBe(surface)
  })

  it('picks the largest svg.recharts-surface when legend icons are also surfaces', () => {
    const container = document.createElement('div')
    const legendIcon = document.createElement('svg')
    legendIcon.setAttribute('class', 'recharts-surface')
    legendIcon.setAttribute('width', '14')
    legendIcon.setAttribute('height', '14')
    const main = document.createElement('svg')
    main.setAttribute('class', 'recharts-surface')
    main.setAttribute('width', '600')
    main.setAttribute('height', '320')
    container.appendChild(legendIcon)
    container.appendChild(main)
    expect(findChartSvgForExport(container)).toBe(main)
  })
})

describe('serializeRechartsWrapperWithLegend', () => {
  it('includes main chart and legend in one svg (foreignObject)', () => {
    const wrapper = document.createElement('div')
    wrapper.className = 'recharts-wrapper'
    wrapper.style.position = 'relative'
    wrapper.style.width = '400px'
    wrapper.style.height = '360px'

    const main = document.createElementNS(SVG_NS, 'svg')
    main.setAttribute('class', 'recharts-surface')
    main.setAttribute('width', '400')
    main.setAttribute('height', '320')
    const path = document.createElementNS(SVG_NS, 'path')
    path.setAttribute('d', 'M0 160 L400 160')
    main.appendChild(path)

    const legend = document.createElement('div')
    legend.className = 'recharts-legend-wrapper'
    legend.style.position = 'absolute'
    legend.style.left = '0'
    legend.style.bottom = '0'
    legend.style.width = '400px'
    legend.style.height = '36px'
    legend.textContent = 'legend label'

    wrapper.appendChild(main)
    wrapper.appendChild(legend)
    document.body.appendChild(wrapper)

    const xml = serializeRechartsWrapperWithLegend(wrapper)
    document.body.removeChild(wrapper)

    expect(xml).toContain('foreignObject')
    expect(xml).toContain('recharts-legend-wrapper')
    expect(xml).toContain('legend label')
    expect(xml).toContain('<path')
  })
})
