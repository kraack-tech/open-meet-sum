import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'
import { OverlayScrollbars } from 'overlayscrollbars'
import 'overlayscrollbars/overlayscrollbars.css'

const app = mount(App, {
  target: document.getElementById('app'),
})

const osOptions = {
  scrollbars: {
    theme: 'os-theme-meetsum',
    autoHide: 'scroll',
    autoHideDelay: 500,
    dragScroll: true,
    clickScroll: true,
  },
}

function initOverlayScrollbars(root = document) {
  const targets = root.querySelectorAll('.os-scroll')
  targets.forEach((el) => {
    if (!OverlayScrollbars(el)) {
      OverlayScrollbars(el, osOptions)
    }
  })
}

initOverlayScrollbars()

const osObserver = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    mutation.addedNodes.forEach((node) => {
      if (!(node instanceof Element)) return
      if (node.matches('.os-scroll')) {
        if (!OverlayScrollbars(node)) {
          OverlayScrollbars(node, osOptions)
        }
      }
      initOverlayScrollbars(node)
    })
  }
})

osObserver.observe(document.body, { childList: true, subtree: true })

export default app
