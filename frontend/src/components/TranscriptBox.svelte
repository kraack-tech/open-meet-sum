<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let content: string = '';
  export let placeholder: string = '';
  export let highlightMap: Record<number, number> = {};
  export let phraseHighlights: { phrase: string; color: number }[] = [];
  export let speakerClickEnabled = false;
  export let clickableSpeakers: string[] = [];

  let editableDiv: HTMLDivElement;
  let lastHighlightMapStr = '';
  let lastPhraseHighlightsStr = '';
  let lastContentFromExternal = '';
  let lastSpeakerClickEnabled = false;
  let lastClickableSpeakersStr = '';
  const dispatch = createEventDispatcher<{
    speakerclick: { lineNumber: number; speaker: string };
  }>();
  

  function escapeHtml(text: string) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function handleInput(e: Event) {
    const target = e.target as HTMLDivElement;
    content = target.innerText || '';
  }

  function renderLineHtml(line: string, lineNumber: number, map: Record<number, number>) {
    const speakerRegex = /^(?:\[(\d{2}:\d{2}(?::\d{2})?)\]\s*)?([^:\n]{1,80}):\s*(.*)$/;
    const match = line.match(speakerRegex);
    const colorIndex = map[lineNumber];

    let rendered = '';
    if (match && speakerClickEnabled) {
      const timestamp = match[1] ? `[${match[1]}] ` : '';
      const speaker = (match[2] || '').trim();
      const text = match[3] || '';
      const canClick = clickableSpeakers.includes(speaker);
      const speakerClass = canClick ? 'speaker-chip is-clickable' : 'speaker-chip';
      const lineAttr = String(lineNumber);
      rendered = `${escapeHtml(timestamp)}<span class="${speakerClass}" data-speaker="${escapeHtml(speaker)}" data-line="${lineAttr}">${escapeHtml(speaker)}</span>: ${escapeHtml(text)}`;
    } else {
      rendered = escapeHtml(line || '');
    }

    if (!rendered) {
      rendered = '&nbsp;';
    }

    if (colorIndex) {
      return `<span class="hl-${colorIndex}">${rendered}</span>`;
    }
    return rendered;
  }

  function handleClick(e: MouseEvent) {
    if (!speakerClickEnabled) return;
    const target = e.target as HTMLElement;
    const speakerEl = target.closest('.speaker-chip.is-clickable') as HTMLElement | null;
    if (!speakerEl) return;

    const speaker = speakerEl.getAttribute('data-speaker') || '';
    const lineRaw = speakerEl.getAttribute('data-line') || '';
    const lineNumber = Number(lineRaw);
    if (!speaker || Number.isNaN(lineNumber)) return;
    dispatch('speakerclick', { lineNumber, speaker });
  }

  function generateHtml(text: string, map: Record<number, number>, phrases: { phrase: string; color: number }[]) {
    if (!text) return '';
    
    // Use phrase-level highlighting if available
    if (phrases && phrases.length > 0 && !speakerClickEnabled) {
      let html = escapeHtml(text);
      
      // Sort phrases by length (longest first) to avoid partial matches  
      const sortedPhrases = [...phrases].sort((a, b) => b.phrase.length - a.phrase.length);
      
      sortedPhrases.forEach(({ phrase, color }) => {
        // Case-insensitive search for the phrase
        const regex = new RegExp(`(${phrase.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')})`, 'gi');
        html = html.replace(regex, `<span class="hl-${color}">$1</span>`);
      });
      
      return html.replace(/\n/g, '<br/>');
    }
    
    // Fallback to line-level highlighting
    const html = text
      .split('\n')
      .map((line, index) => {
        return renderLineHtml(line, index + 1, map);
      })
      .join('<br/>');
    
    return html;
  }

  // Update div when highlightMap, phraseHighlights, or content changes externally
  $: {
    const mapStr = JSON.stringify(highlightMap);
    const phrasesStr = JSON.stringify(phraseHighlights);
    const clickableSpeakersStr = JSON.stringify(clickableSpeakers);
    const currentInnerText = editableDiv?.innerText || '';
    const mapChanged = mapStr !== lastHighlightMapStr;
    const phrasesChanged = phrasesStr !== lastPhraseHighlightsStr;
    const clickModeChanged = speakerClickEnabled !== lastSpeakerClickEnabled;
    const speakersChanged = clickableSpeakersStr !== lastClickableSpeakersStr;
    const contentChangedExternally = content !== currentInnerText && content !== lastContentFromExternal;
    
    if (editableDiv && (mapChanged || phrasesChanged || clickModeChanged || speakersChanged || contentChangedExternally)) {
      lastHighlightMapStr = mapStr;
      lastPhraseHighlightsStr = phrasesStr;
      lastSpeakerClickEnabled = speakerClickEnabled;
      lastClickableSpeakersStr = clickableSpeakersStr;
      lastContentFromExternal = content;
      const newHtml = generateHtml(content, highlightMap, phraseHighlights);
      editableDiv.innerHTML = newHtml;
    }
  }
</script>

<div class="box">
  <div
    bind:this={editableDiv}
    contenteditable="true"
    class="editor"
    class:empty={!content}
    data-placeholder={placeholder}
    on:input={handleInput}
    on:click={handleClick}
  ></div>
</div>

<style>
  .box {
    background: #1e1e1e;
    border: 1px solid #333;
    border-radius: 12px;
    width: 100%;
    height: clamp(120px, 24vh, 280px);
    overflow: hidden;
    margin: 0;
    position: relative;
    text-align: left;
  }

  .editor {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    padding: 14px 12px 12px;
    background: transparent;
    color: #ffffff;
    border: none;
    outline: none;
    font-size: var(--ms-fs-body);
    line-height: var(--ms-line-body);
    font-family: var(--ms-font-family);
    overflow-y: scroll;
    scrollbar-gutter: stable;
    white-space: pre-wrap;
    word-break: break-word;
    text-align: left;
  }

  .editor.empty:before {
    content: attr(data-placeholder);
    color: #888;
    pointer-events: none;
  }

  :global(.hl-1) { background: rgba(255, 209, 102, 0.35); border-radius: 4px; padding: 0 2px; }
  :global(.hl-2) { background: rgba(74, 222, 128, 0.35); border-radius: 4px; padding: 0 2px; }
  :global(.hl-3) { background: rgba(96, 165, 250, 0.35); border-radius: 4px; padding: 0 2px; }
  :global(.hl-4) { background: rgba(244, 114, 182, 0.35); border-radius: 4px; padding: 0 2px; }
  :global(.hl-5) { background: rgba(250, 204, 21, 0.35); border-radius: 4px; padding: 0 2px; }

  :global(:root[data-theme='light'] .hl-1) { background: rgba(245, 158, 11, 0.26); }
  :global(:root[data-theme='light'] .hl-2) { background: rgba(34, 197, 94, 0.24); }
  :global(:root[data-theme='light'] .hl-3) { background: rgba(59, 130, 246, 0.24); }
  :global(:root[data-theme='light'] .hl-4) { background: rgba(236, 72, 153, 0.23); }
  :global(:root[data-theme='light'] .hl-5) { background: rgba(234, 179, 8, 0.26); }

  :global(.speaker-chip) { font-weight: 600; }
  :global(.speaker-chip.is-clickable) { cursor: pointer; text-decoration: underline; text-decoration-style: dotted; }

  :global(:root[data-theme='light']) .box {
    background: #ffffff;
    border-color: #d6d9df;
  }

  :global(:root[data-theme='light']) .editor {
    color: #111827;
  }

  :global(:root[data-theme='light']) .editor.empty:before {
    color: #64748b;
  }
</style>
