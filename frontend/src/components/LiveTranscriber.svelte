<script lang="ts">
  import { createEventDispatcher, onDestroy } from 'svelte';
  import { getAPIBaseURL, getWSURL } from '../lib/config.js';
  import TranscriptBox from './TranscriptBox.svelte';
  import { exportSummaryPdf, exportTranscriptTxt } from '../lib/exporters';

  const dispatch = createEventDispatcher();

  type SummaryItem = {
    text: string;
    sources: number[];
    matched_phrases?: string[];
    source_texts?: string[];
    point_speakers?: string[];
  };

  type HitlItem = {
    confidence: 'high' | 'medium' | 'low';
    needs_confirmation: boolean;
    assumption: string;
    clarification_question: string;
    status: 'pending' | 'accepted' | 'conversing';
  };

  type ConversationMessage = {
    role: 'user' | 'assistant';
    content: string;
  };

  let transcript = '';
  let summary = '';
  let summaryModelLabel = '';
  let hitlModelLabel = '';
  let currentMeetingId = '';
  let summaryItems: SummaryItem[] = [];
  let hitlItems: HitlItem[] = [];
  let conversations: Record<number, ConversationMessage[]> = {};
  let conversationInput: Record<number, string> = {};
  let conversationOpen: Record<number, boolean> = {};
  let conversing: Record<number, boolean> = {};
  let currentRevisedBullets: Record<number, string> = {};
  let dismissedReview: Record<number, boolean> = {};
  let userFlagged: Record<number, boolean> = {};
  let reviewableIndices: number[] = [];
  let flagMode = false;
  let highlightSources = false;
  let showPointSpeakers = false;
  let showSummary = false;
  let showFinish = false;

  export let isRecording = false; // export so parent can bind
  export let isPaused = false;
  export let attendees: string[] = [];

  let audioContext: AudioContext;
  let processor: ScriptProcessorNode;
  let buffer: Float32Array[] = [];
  let fullBuffer: Float32Array[] = [];
  let chunkInterval: any;
  let audioSampleRate = 44100;
  let isFinalizing = false;
  let isFinishing = false;  // Prevents websocket appends during finish
  let chunkStartSec = 0;
  let meetingStartedAt: Date | null = null;

  const WS_URL = getWSURL('ws-transcribe');
  const CHUNK_MS = 30000;
  const OVERLAP_MS = 3000;

  export let enableSpeakers = false;

  let lastSpeaker: string | null = null;
  let lastEnded = true;
  let lastLineText = '';

  type AttributedLine = {
    key: string;
    lineNumber: number;
    timestamp: string;
    speaker: string;
    text: string;
  };

  const speakerLineRegex = /^(?:\[(\d{2}:\d{2}(?::\d{2})?)\]\s*)?([^:\n]{1,80}):\s*(.*)$/;
  let attributedLines: AttributedLine[] = [];
  let speakerOptions: string[] = [];
  let manualSpeakerOptions: string[] = [];
  let manualSpeakerDraft = '';
  let attributionMode = false;
  let selectedLineNumber = 0;
  let selectedLineTimestamp = '';
  let selectedSpeaker = '';

  function normalizeSpeakerName(name: string): string {
    return String(name || '').replace(/\s+/g, ' ').trim();
  }

  function addManualSpeakerOption() {
    const name = normalizeSpeakerName(manualSpeakerDraft);
    if (!name) return;
    if (speakerOptions.some((existing) => existing.toLowerCase() === name.toLowerCase())) {
      selectedSpeaker = speakerOptions.find((existing) => existing.toLowerCase() === name.toLowerCase()) || name;
      manualSpeakerDraft = '';
      return;
    }
    manualSpeakerOptions = [...manualSpeakerOptions, name];
    selectedSpeaker = name;
    manualSpeakerDraft = '';
  }

  function getEffectiveAttendees(): string[] {
    const merged = [...(attendees || []), ...manualSpeakerOptions];
    const seen = new Set<string>();
    const ordered: string[] = [];
    merged.forEach((name) => {
      const normalized = normalizeSpeakerName(name);
      if (!normalized) return;
      const key = normalized.toLowerCase();
      if (key === 'unknown' || seen.has(key)) return;
      seen.add(key);
      ordered.push(normalized);
    });
    return ordered;
  }

  // Toggle recording/pause
  export async function toggleMeeting() {
    if (!isRecording) {
      transcript = '';
      summary = '';
      showSummary = false;
      highlightSources = false;
      showPointSpeakers = false;
      summaryItems = [];
      hitlItems = [];
      conversations = {};
      conversationInput = {};
      conversationOpen = {};
      conversing = {};
      currentRevisedBullets = {};
      dismissedReview = {};
      userFlagged = {};
      flagMode = false;
      lastSpeaker = null;
      lastEnded = true;
      lastLineText = '';
      fullBuffer = [];
      chunkStartSec = 0;

      // START meeting
      meetingStartedAt = new Date();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new AudioContext();
      audioSampleRate = audioContext.sampleRate;
      const source = audioContext.createMediaStreamSource(stream);
      processor = audioContext.createScriptProcessor(4096, 1, 1);

      source.connect(processor);
      processor.connect(audioContext.destination);

      processor.onaudioprocess = (e) => {
        if (isPaused) return;
        const chunk = e.inputBuffer.getChannelData(0).slice();
        buffer.push(chunk);
        fullBuffer.push(chunk);
      };

      chunkInterval = setInterval(sendChunk, CHUNK_MS);

      isRecording = true;
      showFinish = true; // ✅ Show Finish immediately
      isPaused = false;
    } else {
      // PAUSE/resume meeting
      togglePause();
    }
  }

  export async function togglePause() {
    if (!isRecording) return;

    isPaused = !isPaused;

    if (isPaused) {
      if (chunkInterval) clearInterval(chunkInterval);
      if (processor) processor.disconnect();
      if (audioContext) audioContext.close();
    } else {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      processor = audioContext.createScriptProcessor(4096, 1, 1);

      source.connect(processor);
      processor.connect(audioContext.destination);

      processor.onaudioprocess = (e) => {
        if (isPaused) return;
        const chunk = e.inputBuffer.getChannelData(0).slice();
        buffer.push(chunk);
        fullBuffer.push(chunk);
      };

      chunkInterval = setInterval(sendChunk, CHUNK_MS);
    }
  }

  function stopRecording() {
    if (!isRecording) return;
    

    if (chunkInterval) clearInterval(chunkInterval);
    // Do NOT send final chunk - finalization will process complete audio
    // if (buffer.length) sendChunk();

    if (processor) processor.disconnect();
    if (audioContext) audioContext.close();

    isRecording = false;
    isPaused = false;
    
  }

  async function finishMeeting() {
    isFinishing = true;
    stopRecording();
    showFinish = false;
    await finalizeMeeting();
    isFinishing = false;
  }

  async function sendChunk() {
    if (!buffer.length) return;

    const flat = flattenBuffers(buffer);
    const overlapSamples = Math.floor((audioSampleRate * OVERLAP_MS) / 1000);
    const tailStart = Math.max(0, flat.length - overlapSamples);
    const tail = flat.slice(tailStart);
    buffer = tail.length ? [tail] : [];

    const wavBlob = encodeWAV(flat, audioSampleRate);
    const offsetSec = chunkStartSec;
    const advanceSamples = Math.max(0, flat.length - overlapSamples);
    chunkStartSec += advanceSamples / audioSampleRate;
    const attendeesParam = encodeURIComponent(JSON.stringify(getEffectiveAttendees()));

    const socket = new WebSocket(
      `${WS_URL}?speakers=${enableSpeakers ? '1' : '0'}&offset=${offsetSec}&attendees=${attendeesParam}`
    );
    socket.binaryType = 'arraybuffer';
    socket.onopen = async () => {
      await wavBlob.arrayBuffer().then(buf => socket.send(buf));
    };
    socket.onmessage = e => {
      const data = JSON.parse(e.data);

      if (Array.isArray(data.segments)) {
        for (const seg of data.segments) {
          appendSegment(seg.speaker ?? null, seg.text ?? '', seg.start ?? null);
        }
        return;
      }

      appendSegment(data.speaker ?? null, data.text ?? '', data.start ?? null);
    };
  }

  async function finalizeMeeting() {
    if (!fullBuffer.length || isFinalizing) return;
    isFinalizing = true;
    

    const flat = flattenBuffers(fullBuffer);
    const wavBlob = encodeWAV(flat, audioSampleRate);
    const file = new File([wavBlob], 'meeting.wav', { type: 'audio/wav' });

    const formData = new FormData();
    formData.append('file', file);
    formData.append('speakers', enableSpeakers ? '1' : '0');
    formData.append('attendees', JSON.stringify(getEffectiveAttendees()));
    const authToken = localStorage.getItem('meetsum_token') || '';

    try {
      const res = await fetch(`${getAPIBaseURL()}/finalize-meeting`, {
        method: 'POST',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
        body: formData,
      });
      const data = await res.json();
      currentMeetingId = data?.meeting_id || currentMeetingId;
      
      transcript = data.transcript;  // Force complete replacement
      if ((data?.transcript || '').trim()) {
        dispatch('meetingSaved');
      }
      
      summary = '';
      summaryItems = [];
      hitlItems = [];
      conversations = {};
      conversationInput = {};
      conversationOpen = {};
      conversing = {};
      currentRevisedBullets = {};
      dismissedReview = {};
      highlightSources = false;
      showPointSpeakers = false;
      showSummary = false;
    } catch (err) {
      console.error(err);
    } finally {
      isFinalizing = false;
      fullBuffer = [];
    }
  }

  function flattenBuffers(chunks: Float32Array[]) {
    const flat = new Float32Array(chunks.reduce((acc, cur) => acc + cur.length, 0));
    let offset = 0;
    for (let b of chunks) {
      flat.set(b, offset);
      offset += b.length;
    }
    return flat;
  }

  function appendSegment(speaker: string | null, text: string, start: number | null) {
    if (isFinishing || isFinalizing) {
      return;
    }
    const clean = text.trim();
    if (!clean) return;

    const speakerKey = enableSpeakers ? (speaker ?? 'Unknown') : null;
    const timeLabel = start !== null ? `[${formatTimestamp(start)}] ` : '';
    const label = enableSpeakers ? `${timeLabel}${speakerKey}: ` : timeLabel;
    const endsSentence = /[.!?]$/.test(clean);

    if (speakerKey && speakerKey === lastSpeaker && !lastEnded) {
      if (lastLineText && clean.startsWith(lastLineText)) {
        const suffix = clean.slice(lastLineText.length).trim();
        if (suffix) {
          transcript += ` ${suffix}`;
          lastLineText = `${lastLineText} ${suffix}`.trim();
        }
      } else if (lastLineText && lastLineText.endsWith(clean)) {
        // skip duplicate overlap
      } else {
        transcript += ` ${clean}`;
        lastLineText = `${lastLineText} ${clean}`.trim();
      }
    } else {
      transcript += `${label}${clean}\n`;
      lastLineText = clean;
    }

    lastSpeaker = speakerKey;
    lastEnded = endsSentence;
  }

  function formatTimestamp(seconds: number) {
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours > 0) {
      return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }
    return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  function parseAttributedLines(text: string): AttributedLine[] {
    return text
      .split('\n')
      .map((line, index) => {
        const match = line.match(speakerLineRegex);
        if (!match) return null;
        return {
          key: String(index),
          lineNumber: index + 1,
          timestamp: match[1] || '',
          speaker: (match[2] || 'Unknown').trim() || 'Unknown',
          text: (match[3] || '').trim(),
        };
      })
      .filter((item): item is AttributedLine => item !== null);
  }

  function applySpeakerToSelectedLine(nextSpeaker?: string) {
    if (!enableSpeakers) return;
    if (!transcript || !selectedLineNumber) return;
    const lineIndex = selectedLineNumber - 1;
    if (Number.isNaN(lineIndex) || lineIndex < 0) return;

    const speakerLabel = (nextSpeaker || selectedSpeaker || '').trim();
    if (!speakerLabel) return;
    const lines = transcript.split('\n');
    if (lineIndex >= lines.length) return;

    const match = lines[lineIndex].match(speakerLineRegex);
    if (!match) return;

    const timestamp = match[1] ? `[${match[1]}] ` : '';
    const text = (match[3] || '').trim();
    lines[lineIndex] = `${timestamp}${speakerLabel}: ${text}`;
    transcript = lines.join('\n');

    summary = '';
    summaryItems = [];
    hitlItems = [];
    conversations = {};
    conversationInput = {};
    conversationOpen = {};
    conversing = {};
    currentRevisedBullets = {};
    dismissedReview = {};
    userFlagged = {};
    flagMode = false;
    highlightSources = false;
    showPointSpeakers = false;
    showSummary = false;
  }

  function finishAttribution() {
    attributionMode = false;
    selectedLineNumber = 0;
    selectedLineTimestamp = '';
    selectedSpeaker = '';
    manualSpeakerDraft = '';
  }

  function handleSpeakerClick(e: CustomEvent<{ lineNumber: number; speaker: string }>) {
    if (!enableSpeakers || !attributionMode) return;
    const { lineNumber, speaker } = e.detail;
    const normalizedClickedSpeaker = normalizeSpeakerName(speaker);
    selectedLineNumber = lineNumber;
    const selectedLine = attributedLines.find((line) => line.lineNumber === lineNumber);
    selectedLineTimestamp = selectedLine?.timestamp || '';
    if (normalizedClickedSpeaker && speakerOptions.some((option) => option.toLowerCase() === normalizedClickedSpeaker.toLowerCase())) {
      selectedSpeaker = speakerOptions.find((option) => option.toLowerCase() === normalizedClickedSpeaker.toLowerCase()) || normalizedClickedSpeaker;
      return;
    }
    if (normalizedClickedSpeaker && !manualSpeakerOptions.some((option) => option.toLowerCase() === normalizedClickedSpeaker.toLowerCase())) {
      manualSpeakerOptions = [...manualSpeakerOptions, normalizedClickedSpeaker];
      selectedSpeaker = normalizedClickedSpeaker;
      return;
    }
    selectedSpeaker = speakerOptions[0] || '';
  }

  function getTranscriptPhraseHighlights() {
    if (!summaryItems.length) return [];
    const phrases: { phrase: string; color: number }[] = [];

    summaryItems.forEach((item, index) => {
      const color = Math.min(index + 1, 5);
      if (item.matched_phrases && item.matched_phrases.length) {
        item.matched_phrases.forEach((phrase) => {
          phrases.push({ phrase, color });
        });
      }
    });

    return phrases;
  }

  function getSummaryHighlightMap() {
    const map: Record<number, number> = {};
    const lines = summary.split('\n');
    let bulletIndex = 0;
    lines.forEach((line, index) => {
      if (line.trim().startsWith('-')) {
        const color = Math.min(bulletIndex + 1, 5);
        map[index + 1] = color;
        bulletIndex += 1;
      }
    });
    return map;
  }

  function extractSpeakerFromTranscriptLine(line: string): string | null {
    const match = line.match(/^\s*(?:\[(?:\d{2}:\d{2}(?::\d{2})?)\]\s*)?([^:\n]{1,80}):\s*/);
    if (!match) return null;
    const speaker = String(match[1] || '').trim();
    return speaker || null;
  }

  function normalizeSourceLineIndex(sourceRef: unknown, totalLines: number): number | null {
    const toIndexFromLineNumber = (value: number): number | null => {
      if (!Number.isFinite(value)) return null;
      const n = Math.trunc(value);
      if (n >= 1 && n <= totalLines) return n - 1;
      if (n >= 0 && n < totalLines) return n;
      return null;
    };

    if (typeof sourceRef === 'number') return toIndexFromLineNumber(sourceRef);
    if (typeof sourceRef === 'string') return toIndexFromLineNumber(Number(sourceRef.trim()));
    if (sourceRef && typeof sourceRef === 'object') {
      const obj = sourceRef as Record<string, unknown>;
      return (
        toIndexFromLineNumber(Number(obj.line_number)) ??
        toIndexFromLineNumber(Number(obj.line)) ??
        toIndexFromLineNumber(Number(obj.index))
      );
    }
    return null;
  }

  function collectPointSpeakers(index: number): string[] {
    const item = summaryItems[index];
    if (!item) return [];

    const persistedSpeakers = Array.isArray((item as any).point_speakers)
      ? (item as any).point_speakers.map((v: unknown) => String(v || '').trim()).filter(Boolean)
      : [];
    if (persistedSpeakers.length) return persistedSpeakers;

    const transcriptLines = transcript.split('\n');
    if (!transcriptLines.length) return [];

    const speakers: string[] = [];
    const seen = new Set<string>();
    const pushSpeaker = (speaker: string | null) => {
      if (!speaker) return;
      const normalized = speaker.trim();
      if (!normalized) return;
      const key = normalized.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      speakers.push(normalized);
    };

    const sourceRefs = Array.isArray((item as any).sources) ? (item as any).sources : [];
    sourceRefs.forEach((sourceRef: unknown) => {
      const idx = normalizeSourceLineIndex(sourceRef, transcriptLines.length);
      if (idx === null) return;
      pushSpeaker(extractSpeakerFromTranscriptLine(transcriptLines[idx] || ''));
    });

    if (speakers.length) return speakers;

    const sourceTextsDirect = Array.isArray((item as any).source_texts) ? (item as any).source_texts : [];
    sourceTextsDirect.forEach((chunk: unknown) => {
      pushSpeaker(extractSpeakerFromTranscriptLine(String(chunk || '')));
    });

    if (speakers.length) return speakers;

    const phrases = Array.isArray((item as any).matched_phrases) ? (item as any).matched_phrases : [];
    phrases.forEach((phrase: unknown) => {
      const needle = String(phrase || '').trim().toLowerCase();
      if (!needle) return;
      for (const line of transcriptLines) {
        if (!line.toLowerCase().includes(needle)) continue;
        pushSpeaker(extractSpeakerFromTranscriptLine(line));
      }
    });

    if (speakers.length) return speakers;

    const sourceTexts = Array.isArray((item as any).source_texts) ? (item as any).source_texts : [];
    sourceTexts.forEach((chunk: unknown) => {
      const needle = String(chunk || '').trim().toLowerCase();
      if (!needle) return;
      for (const line of transcriptLines) {
        if (!line.toLowerCase().includes(needle)) continue;
        pushSpeaker(extractSpeakerFromTranscriptLine(line));
      }
    });

    if (speakers.length) return speakers;

    // Final fallback: lexical overlap between point text and speaker-attributed transcript lines.
    const pointText = String((item as any).text || '').toLowerCase();
    const pointTokens = new Set((pointText.match(/[a-z0-9]+/g) || []).filter((t) => t.length > 2));
    if (!pointTokens.size) return speakers;

    const scored: Array<{ speaker: string; score: number }> = [];
    transcriptLines.forEach((line) => {
      const speaker = extractSpeakerFromTranscriptLine(line);
      if (!speaker) return;
      const lineTokens = new Set((line.toLowerCase().match(/[a-z0-9]+/g) || []).filter((t) => t.length > 2));
      const overlap = Array.from(pointTokens).filter((token) => lineTokens.has(token)).length;
      if (overlap > 0) scored.push({ speaker, score: overlap });
    });

    scored
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .forEach((entry) => pushSpeaker(entry.speaker));

    if (speakers.length) return speakers;

    const counts: Record<string, number> = {};
    transcriptLines.forEach((line) => {
      const speaker = extractSpeakerFromTranscriptLine(line);
      if (!speaker) return;
      counts[speaker] = (counts[speaker] || 0) + 1;
    });

    Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .forEach(([speaker]) => pushSpeaker(speaker));

    return speakers;
  }

  function getPointSpeakerSuffix(index: number): string {
    let speakers = collectPointSpeakers(index);
    if (!speakers.length) {
      const transcriptSpeakers = Array.from(
        new Set(
          transcript
            .split('\n')
            .map((line) => extractSpeakerFromTranscriptLine(line))
            .filter((name): name is string => Boolean(name && name.trim()))
        )
      );
      if (transcriptSpeakers.length) {
        speakers = transcriptSpeakers.slice(0, 2);
      }
    }
    if (!speakers.length && attendees.length) {
      speakers = attendees.slice(0, 2);
    }
    if (!speakers.length) {
      speakers = ['Unknown'];
    }
    return speakers.length ? ` [${speakers.join(', ')}]` : '';
  }

  function formatPointTextWithSpeakers(text: string, index: number): string {
    if (!showPointSpeakers) return text;
    return `${text}${getPointSpeakerSuffix(index)}`;
  }

  function extractCurrentSummaryBullets() {
    const bullets = summary
      .split('\n')
      .map((line) => line.replace(/^\s*[-•]\s*/, '').trim())
      .filter(Boolean);

    if (bullets.length) return bullets;
    return summaryItems.map((item) => item.text).filter(Boolean);
  }

  function normalizeBulletText(text: string) {
    return String(text || '')
      .replace(/\s*\[[^\]]+\]\s*$/, '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, ' ');
  }

  function findMatchingSummaryItemIndex(bulletText: string, usedIndices: Set<number>): number | null {
    const normalizedBullet = normalizeBulletText(bulletText);
    if (!normalizedBullet) return null;

    for (let index = 0; index < summaryItems.length; index += 1) {
      if (usedIndices.has(index)) continue;
      if (normalizeBulletText(summaryItems[index]?.text) === normalizedBullet) {
        return index;
      }
    }

    let bestIndex: number | null = null;
    let bestScore = 0;
    const bulletTokens = new Set(normalizedBullet.match(/[a-z0-9]+/g) || []);
    if (!bulletTokens.size) return null;

    for (let index = 0; index < summaryItems.length; index += 1) {
      if (usedIndices.has(index)) continue;
      const itemText = normalizeBulletText(summaryItems[index]?.text);
      if (!itemText) continue;
      const itemTokens = new Set(itemText.match(/[a-z0-9]+/g) || []);
      const score = Array.from(bulletTokens).filter((token) => itemTokens.has(token)).length;
      if (score > bestScore) {
        bestScore = score;
        bestIndex = index;
      }
    }

    return bestScore >= 2 ? bestIndex : null;
  }

  function getDisplayedSummaryBullets() {
    const bullets = extractCurrentSummaryBullets();
    if (!showPointSpeakers) return bullets;

    const usedIndices = new Set<number>();
    return bullets.map((bullet) => {
      const itemIndex = findMatchingSummaryItemIndex(bullet, usedIndices);
      if (itemIndex === null) return bullet;
      usedIndices.add(itemIndex);
      return `${bullet}${getPointSpeakerSuffix(itemIndex)}`;
    });
  }

  function getSummaryDisplayText() {
    if (!showPointSpeakers) return summary;
    const bullets = getDisplayedSummaryBullets();
    if (!bullets.length) return summary;
    return bullets.map((bullet) => `- ${bullet}`).join('\n');
  }

  $: displayedSummary = showPointSpeakers && summaryItems.length
    ? getSummaryDisplayText()
    : summary;

  $: if (highlightSources) {
    getTranscriptPhraseHighlights();
    getSummaryHighlightMap();
  }

  $: attributedLines = enableSpeakers ? parseAttributedLines(transcript) : [];

  $: if (!enableSpeakers) {
    attributionMode = false;
    selectedLineNumber = 0;
    selectedLineTimestamp = '';
    selectedSpeaker = '';
  }

  $: speakerOptions = (() => {
    const ordered: string[] = [];
    const seen = new Set<string>();
    const add = (name: string) => {
      const normalized = normalizeSpeakerName(name);
      if (!normalized) return;
      const key = normalized.toLowerCase();
      if (key === 'unknown' || seen.has(key)) return;
      seen.add(key);
      ordered.push(normalized);
    };

    // Primary source: meeting attendees
    (attendees || []).forEach(add);
    // Manual additions for late joiners or corrections
    manualSpeakerOptions.forEach(add);
    // Fallback: speakers already detected in transcript
    attributedLines.map((line) => line.speaker).forEach(add);

    return ordered;
  })();

  $: {
    if (!attributedLines.length) {
      selectedLineNumber = 0;
      selectedLineTimestamp = '';
      selectedSpeaker = '';
    } else if (!speakerOptions.includes(selectedSpeaker)) {
      const selectedLine = attributedLines.find((line) => line.lineNumber === selectedLineNumber);
      if (selectedLine && speakerOptions.includes(selectedLine.speaker)) {
        selectedSpeaker = selectedLine.speaker;
      } else {
        selectedSpeaker = speakerOptions[0] || '';
      }
    }
  }

  $: {
    // Keep only manual speakers that are not already represented by attendees.
    const attendeeSet = new Set((attendees || []).map((name) => normalizeSpeakerName(name).toLowerCase()).filter(Boolean));
    const filteredManual = manualSpeakerOptions.filter((name) => !attendeeSet.has(normalizeSpeakerName(name).toLowerCase()));
    if (filteredManual.length !== manualSpeakerOptions.length) {
      manualSpeakerOptions = filteredManual;
    }
  }

  function encodeWAV(samples: Float32Array, sampleRate: number) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, 'data');
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
      let s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }

    return new Blob([view], { type: 'audio/wav' });
  }

  function writeString(view: DataView, offset: number, str: string) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  }

  async function summarizeMeeting() {
    if (!transcript) return;
    const authToken = localStorage.getItem('meetsum_token') || '';
    try {
      const res = await fetch(`${getAPIBaseURL()}/summarize-hitl`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ transcript }),
      });
      const data = await res.json();
      currentMeetingId = data?.meeting_id || currentMeetingId;
      summary = data.summary;
      summaryModelLabel = data?.model_used?.label || '';
      hitlModelLabel = data?.hitl_model_used?.label || '';
      summaryItems = data.summary_items || [];
      hitlItems = normalizeHitlItems(data.hitl_items || [], summaryItems);
      conversations = {};
      conversationInput = {};
      conversationOpen = {};
      conversing = {};
      currentRevisedBullets = {};
      dismissedReview = {};
      userFlagged = {};
      flagMode = false;
      highlightSources = false;
      showSummary = true;
      dispatch('meetingSaved');
    } catch (err) {
      console.error(err);
    }
  }

  function normalizeHitlItems(rawItems: any[], items: SummaryItem[]): HitlItem[] {
    const normalized: HitlItem[] = [];
    for (let index = 0; index < items.length; index += 1) {
      const fallback = defaultHitlItem(items[index]?.text || '');
      const raw = rawItems?.[index] || {};
      const confidenceRaw = String(raw.confidence || fallback.confidence).toLowerCase();
      const confidence = (confidenceRaw === 'high' || confidenceRaw === 'low' || confidenceRaw === 'medium')
        ? confidenceRaw
        : 'medium';

      normalized.push({
        confidence,
        needs_confirmation: Boolean(raw.needs_confirmation ?? fallback.needs_confirmation),
        assumption: String(raw.assumption || fallback.assumption),
        clarification_question: String(raw.clarification_question || fallback.clarification_question),
        status: 'pending',
      });
    }
    return normalized;
  }

  function defaultHitlItem(bulletText: string): HitlItem {
    return {
      confidence: 'medium',
      needs_confirmation: true,
      assumption: 'This point may rely on interpretation from the transcript context.',
      clarification_question: `Can you confirm this point is accurate: ${bulletText}?`,
      status: 'pending',
    };
  }

  function setConversationOpen(index: number, value: boolean) {
    conversationOpen = { ...conversationOpen, [index]: value };
  }

  function setConversationInput(index: number, value: string) {
    conversationInput = { ...conversationInput, [index]: value };
  }

  function setConversing(index: number, value: boolean) {
    conversing = { ...conversing, [index]: value };
  }

  async function persistSummaryEdits() {
    if (!currentMeetingId) return;
    const authToken = localStorage.getItem('meetsum_token') || '';
    try {
      await fetch(`${getAPIBaseURL()}/summary/save-edits`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          meeting_id: currentMeetingId,
          summary_text: summary,
          summary_items: summaryItems,
        }),
      });
      dispatch('meetingSaved');
    } catch (err) {
      console.error('Error persisting summary edits:', err);
    }
  }

  async function acceptBullet(index: number) {
    const revisedBullet = currentRevisedBullets[index];
    if (revisedBullet) {
      summaryItems[index] = {
        ...summaryItems[index],
        text: revisedBullet,
      };
      summaryItems = [...summaryItems];

      const bullets = summaryItems.map((item) => item.text);
      summary = bullets.map((b) => `- ${b}`).join('\n');
    }

    dismissedReview = { ...dismissedReview, [index]: true };
    if (!hitlItems[index]) return;
    hitlItems[index] = {
      ...hitlItems[index],
      needs_confirmation: false,
      status: 'accepted',
      clarification_question: '',
    };
    hitlItems = [...hitlItems];
    setConversationOpen(index, false);
    setConversationInput(index, '');
    conversations = { ...conversations, [index]: [] };
    currentRevisedBullets = { ...currentRevisedBullets, [index]: undefined };
    await persistSummaryEdits();
  }

  function startConversation(index: number) {
    if (!conversations[index]) {
      conversations = { ...conversations, [index]: [] };
    }
    setConversationOpen(index, true);
    if (!conversationInput[index]) {
      setConversationInput(index, '');
    }
  }

  async function sendMessage(index: number) {
    const message = (conversationInput[index] || '').trim();
    if (!message || conversing[index]) return;

    const history = conversations[index] || [];
    const originalBullet = summaryItems[index]?.text || '';

    try {
      setConversing(index, true);

      if (currentRevisedBullets[index] === '__REMOVE__') return;

      // Add user message to conversation
      const userMsg: ConversationMessage = { role: 'user', content: message };
      conversations = {
        ...conversations,
        [index]: [...history, userMsg],
      };
      setConversationInput(index, '');

      const res = await fetch(`${getAPIBaseURL()}/summary/converse-bullet`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transcript,
          original_bullet: originalBullet,
          conversation_history: conversations[index],
          user_message: message,
        }),
      });

      const data = await res.json();

      if (hitlItems[index]?.status === 'accepted') {
        return;
      }

      const assistantResponse = data.assistant_response || 'I understand.';

      if (hitlItems[index]?.status === 'accepted') {
        return;
      }

      const revisedBullet = (data.revised_bullet && data.revised_bullet !== '') ? data.revised_bullet : originalBullet;
      const followUpQuestion = data.follow_up_question || '';

      // Add assistant message
      const assistantMsg: ConversationMessage = {
        role: 'assistant',
        content: `${assistantResponse}${followUpQuestion ? '\n\n' + followUpQuestion : ''}`,
      };
      conversations = {
        ...conversations,
        [index]: [...conversations[index], assistantMsg],
      };

      // Update current revised bullet
      currentRevisedBullets = {
        ...currentRevisedBullets,
        [index]: revisedBullet,
      };

      if (hitlItems[index]) {
        hitlItems[index] = {
          ...hitlItems[index],
          status: 'conversing',
        };
        hitlItems = [...hitlItems];
      }
    } catch (err) {
      console.error(err);
    } finally {
      setConversing(index, false);
    }
  }

  async function commitRevisedBullet(index: number) {
    const revisedBullet = currentRevisedBullets[index];
    if (!revisedBullet) return;

    if (revisedBullet === '__REMOVE__') {
      summaryItems = summaryItems.filter((_, i) => i !== index);
      hitlItems = hitlItems.filter((_, i) => i !== index);
      summary = summaryItems.map((item) => `- ${item.text}`).join('\n');
      currentRevisedBullets = Object.fromEntries(
        Object.entries(currentRevisedBullets).filter(([k]) => Number(k) !== index)
      );
      conversationOpen = { ...conversationOpen, [index]: false };
      await persistSummaryEdits();
      return;
    }

    summaryItems[index] = {
      ...summaryItems[index],
      text: revisedBullet,
    };
    summaryItems = [...summaryItems];

    const bullets = summaryItems.map((item) => item.text);
    summary = bullets.map((b) => `- ${b}`).join('\n');

    await acceptBullet(index);
  }

  function getConfidenceLabel(confidence: HitlItem['confidence']) {
    if (confidence === 'high') return 'High confidence';
    if (confidence === 'low') return 'Low confidence';
    return 'Medium confidence';
  }

  function isReviewable(index: number) {
    if (dismissedReview[index]) return false;
    if (userFlagged[index]) return true;
    const item = hitlItems[index];
    return Boolean(item && item.status !== 'accepted' && item.confidence !== 'high');
  }

  function toggleFlag(index: number) {
    if (userFlagged[index]) {
      userFlagged = { ...userFlagged, [index]: false };
      dismissedReview = { ...dismissedReview, [index]: true };
    } else {
      if (!hitlItems[index]) {
        const newHitl = [...hitlItems];
        while (newHitl.length <= index) {
          newHitl.push({ confidence: 'medium', needs_confirmation: false, assumption: '', clarification_question: '', status: 'pending' });
        }
        newHitl[index] = defaultHitlItem(summaryItems[index]?.text || '');
        hitlItems = newHitl;
      } else {
        hitlItems[index] = {
          ...hitlItems[index],
          status: 'pending',
        };
        hitlItems = [...hitlItems];
      }
      userFlagged = { ...userFlagged, [index]: true };
      dismissedReview = { ...dismissedReview, [index]: false };
    }
  }

  function getExportAttendees(): string[] {
    const merged = [...getEffectiveAttendees(), ...speakerOptions];
    const seen = new Set<string>();
    const ordered: string[] = [];
    merged.forEach((name) => {
      const normalized = normalizeSpeakerName(name);
      if (!normalized) return;
      const key = normalized.toLowerCase();
      if (key === 'unknown' || seen.has(key)) return;
      seen.add(key);
      ordered.push(normalized);
    });
    return ordered;
  }

  function handleExportSummaryPdf() {
    exportSummaryPdf(
      getDisplayedSummaryBullets(),
      getSummaryDisplayText(),
      transcript,
      meetingStartedAt,
      getExportAttendees(),
    );
  }

  function handleExportTranscriptTxt() {
    exportTranscriptTxt(transcript);
  }

  $: {
    summaryItems;
    hitlItems;
    dismissedReview;
    userFlagged;
    reviewableIndices = summaryItems
      .map((_, index) => index)
      .filter((index) => isReviewable(index));
  }

  $: if (!attendees.length && showPointSpeakers) {
    showPointSpeakers = false;
  }

  onDestroy(() => stopRecording());
</script>

<div class="text-box">
  {#if showFinish || transcript}
    <div class="transcript-header-row">
      <h2>Live Transcript</h2>
      {#if enableSpeakers}
        <label class="attribution-toggle">
          <input type="checkbox" bind:checked={attributionMode} />
          Enable speaker attribution
        </label>
      {/if}
    </div>
    <TranscriptBox
      bind:content={transcript}
      placeholder="Live transcript will appear here..."
      highlightMap={{}}
      phraseHighlights={highlightSources ? getTranscriptPhraseHighlights() : []}
      speakerClickEnabled={enableSpeakers && attributionMode}
      clickableSpeakers={speakerOptions}
      on:speakerclick={handleSpeakerClick}
    />
    {#if enableSpeakers && attributionMode}
      <div class="attribution-controls">
        <h3>Attribution Control</h3>
        <div class="attribution-row">
          {#if selectedLineNumber}
            <div class="selected-line">
              <strong>Selected line {selectedLineNumber}</strong>
              <span>Timestamp: {selectedLineTimestamp ? `[${selectedLineTimestamp}]` : 'N/A'}</span>
            </div>
          {:else}
            <div class="selected-line empty">Click a speaker name in the transcript to reassign that line.</div>
          {/if}

          <label>
            Speaker
            <select bind:value={selectedSpeaker} disabled={!speakerOptions.length}>
              {#each speakerOptions as speakerName}
                <option value={speakerName}>{speakerName}</option>
              {/each}
            </select>
          </label>

          <div class="manual-speaker-add">
            <input
              type="text"
              bind:value={manualSpeakerDraft}
              placeholder="Add speaker name"
              on:keydown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  addManualSpeakerOption();
                }
              }}
            />
            <button on:click={addManualSpeakerOption} disabled={!manualSpeakerDraft.trim()}>
              Add speaker
            </button>
          </div>

          <button on:click={() => applySpeakerToSelectedLine()} disabled={!selectedLineNumber || !selectedSpeaker}>
            Apply
          </button>
          <button on:click={() => applySpeakerToSelectedLine('Unknown')} disabled={!selectedLineNumber}>
            Mark Unknown
          </button>
          <button on:click={finishAttribution}>
            Finished
          </button>
        </div>
      </div>
    {/if}
    {#if showFinish}
      <button class="action-button" on:click={finishMeeting}>Finish Meeting</button>
    {:else}
      <button class="action-button" on:click={summarizeMeeting} disabled={!transcript}>Summarize</button>
    {/if}
  {/if}

  {#if showSummary}
    <div class="summary-header">
      <div>
        <h2>Meeting Summary</h2>
        {#if summaryModelLabel || hitlModelLabel}
          <p class="summary-model-meta">
            {#if summaryModelLabel}Summary: {summaryModelLabel}{/if}{#if summaryModelLabel && hitlModelLabel} · {/if}{#if hitlModelLabel}Feedback: {hitlModelLabel}{/if}
          </p>
        {/if}
      </div>
    </div>

    {#if flagMode && summaryItems.length}
      <div class="flag-list-view">
        <p class="flag-instruction">Click a point to flag or unflag it as incorrect. Flagged points will appear in the review panel.</p>
        <ol class="flag-bullets">
          {#each summaryItems as item, index}
            <li
              class="flag-bullet {userFlagged[index] ? 'flagged' : ''}"
              on:click={() => toggleFlag(index)}
              role="button"
              tabindex="0"
              on:keydown={(e) => e.key === 'Enter' && toggleFlag(index)}
            >
              {#if userFlagged[index]}<span class="flag-icon">⚑</span>{/if}
              {item.text}
            </li>
          {/each}
        </ol>
      </div>
    {:else}
      <TranscriptBox
        content={displayedSummary}
        placeholder="Meeting summary..."
        highlightMap={highlightSources ? getSummaryHighlightMap() : {}}
        phraseHighlights={[]}
      />
    {/if}

    {#if summaryItems.length}
      <div class="export-row summary-controls-row">
        <div class="summary-toggles">
          <label class="summary-toggle">
            <input type="checkbox" bind:checked={highlightSources} />
            Highlight sources
          </label>
          {#if attendees.length}
            <label class="summary-toggle">
              <input type="checkbox" bind:checked={showPointSpeakers} />
              Add speakers to points
            </label>
          {/if}
          {#if summaryItems.length}
            <button class="flag-mode-btn {flagMode ? 'active' : ''}" on:click={() => flagMode = !flagMode}>
              {flagMode ? 'Done' : 'Discuss points'}
            </button>
          {/if}
        </div>
      </div>
    {/if}

    {#if !reviewableIndices.length}
      <div class="export-row">
        <details class="export-menu">
          <summary class="action-button export-trigger">Export ▾</summary>
          <div class="export-dropdown">
            <button type="button" on:click={handleExportSummaryPdf}>Export Summary (PDF)</button>
            <button type="button" on:click={handleExportTranscriptTxt}>Export Transcript (TXT)</button>
          </div>
        </details>
      </div>
    {/if}

    {#if reviewableIndices.length}
      <div class="hitl-panel">
        <h3>Review Summary Points</h3>
        {#each reviewableIndices as index (index)}
          {@const item = summaryItems[index]}
          <div class="hitl-card">
            <div class="hitl-card-head">
              <strong>Point {index + 1}</strong>
              <span class={userFlagged[index] ? 'confidence user-flagged' : `confidence ${hitlItems[index]?.confidence || 'medium'}`}>
                {userFlagged[index] ? 'Flagged by you' : getConfidenceLabel(hitlItems[index]?.confidence || 'medium')}
              </span>
            </div>

            {#if currentRevisedBullets[index] === '__REMOVE__'}
              <p class="hitl-bullet hitl-bullet--remove">This point will be removed.</p>
            {:else}
              <p class="hitl-bullet">{currentRevisedBullets[index] || item.text}</p>
            {/if}

            {#if hitlItems[index]?.needs_confirmation && hitlItems[index]?.status !== 'accepted'}
              <div class="hitl-question">
                {#if hitlItems[index]?.assumption}
                  <p><strong>Assumption:</strong> {hitlItems[index].assumption}</p>
                {/if}
              </div>
            {/if}

            {#if hitlItems[index]?.status !== 'accepted' && !conversationOpen[index]}
              <div class="hitl-actions">
                <button on:click={() => acceptBullet(index)}>Accept</button>
                <button on:click={() => startConversation(index)}>Discuss</button>
              </div>
            {/if}

            {#if conversationOpen[index]}
              <div class="conversation-panel">
                <h4>Conversation</h4>
                <div class="conversation-thread">
                  {#each conversations[index] || [] as message}
                    <div class={`message ${message.role}`}>
                      <strong>{message.role === 'user' ? 'You' : 'Assistant'}:</strong>
                      <p>{message.content}</p>
                    </div>
                  {/each}
                </div>

                <div class="conversation-input">
                  {#if currentRevisedBullets[index] === '__REMOVE__'}
                    <p class="remove-confirm-hint">Confirm removal below, or close to keep this point.</p>
                  {:else}
                  <textarea
                    rows="2"
                    value={conversationInput[index] || ''}
                    on:input={(e) => setConversationInput(index, (e.target as HTMLTextAreaElement).value)}
                    placeholder="Tell the assistant what you meant or ask for clarification..."
                    disabled={conversing[index]}
                    on:keydown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage(index);
                      }
                    }}
                  ></textarea>
                  {/if}
                  <div class="hitl-actions">
                    {#if currentRevisedBullets[index] !== '__REMOVE__'}
                    <button on:click={() => sendMessage(index)} disabled={conversing[index] || !conversationInput[index]?.trim()}>
                      {conversing[index] ? 'Sending...' : 'Send'}
                    </button>
                    {/if}
                    <button
                      on:click={() => currentRevisedBullets[index] ? commitRevisedBullet(index) : acceptBullet(index)}
                      disabled={conversing[index]}
                    >
                      {currentRevisedBullets[index] === '__REMOVE__' ? 'Confirm Remove' : 'Accept'}
                    </button>
                    <button on:click={() => setConversationOpen(index, false)} disabled={conversing[index]}>
                      Close
                    </button>
                  </div>
                </div>
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .text-box {
    width: 100%;
    max-width: var(--ms-content-max-width);
    margin: 0 auto;
    padding: 0 24px;
    box-sizing: border-box;
    font-family: inherit;
    font-size: var(--ms-fs-body);
    line-height: var(--ms-line-body);
  }

  .attendee-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    margin: 4px 0 12px;
    color: #a3a3a3;
    font-size: var(--ms-fs-meta);
  }

  .attendee-label {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #a3a3a3;
  }

  .attendee-chip {
    color: #a3a3a3;
    font-weight: 500;
  }

  .action-button {
    margin-top: 10px;
    border-radius: 12px;
    border: 1px solid #3a3a3a;
    padding: 0.5rem 0.95rem;
    background-color: #1a1a1a;
    color: rgba(255, 255, 255, 0.92);
    cursor: pointer;
    transition: border-color 0.2s, background-color 0.2s;
    font-family: inherit;
    font-size: 0.9rem;
    font-weight: 500;
    line-height: 1.2;
  }

  .action-button:hover {
    border-color: #4a4a4a;
    background: #232323;
  }

  .export-row {
    margin-top: 10px;
    display: flex;
    justify-content: flex-start;
  }

  .export-menu {
    position: relative;
  }

  .export-menu summary {
    list-style: none;
  }

  .export-menu summary::-webkit-details-marker {
    display: none;
  }

  .export-trigger {
    margin-top: 0;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    user-select: none;
  }

  .export-dropdown {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    min-width: 240px;
    background: #171717;
    border: 1px solid #333;
    border-radius: 12px;
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    z-index: 20;
    box-shadow: 0 10px 26px rgba(0, 0, 0, 0.35);
  }

  .export-dropdown button {
    width: 100%;
    text-align: left;
    border-radius: 8px;
    border: 1px solid #333;
    padding: 0.5rem 0.7rem;
  }

  h2 {
    color: #ffffff;
    margin: 16px 0 8px;
    font-size: var(--ms-fs-title);
    font-weight: 650;
    line-height: 1.2;
  }

  .summary-header {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .transcript-header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .attribution-toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #c7c7c7;
    font-size: var(--ms-fs-subtitle);
  }

  .summary-toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #c7c7c7;
    font-size: var(--ms-fs-subtitle);
  }

  .summary-toggles {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 2px;
  }

  .summary-controls-row {
    margin-top: 6px;
  }

  .attribution-controls {
    margin: 12px auto 0;
    width: 90%;
    max-width: 1100px;
    text-align: left;
  }

  .attribution-controls h3 {
    margin: 0 0 8px;
    font-size: 1rem;
    font-weight: 500;
    color: #ffffff;
  }

  .attribution-row {
    display: flex;
    gap: 10px;
    align-items: end;
    flex-wrap: wrap;
  }

  .manual-speaker-add {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .manual-speaker-add input {
    min-width: 180px;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid #444;
    background: #1e1e1e;
    color: #ffffff;
    font-family: inherit;
  }

  .selected-line {
    display: flex;
    flex-direction: column;
    gap: 4px;
    color: #c7c7c7;
    max-width: 520px;
    font-size: var(--ms-fs-subtitle);
  }

  .selected-line.empty {
    font-style: italic;
  }

  .attribution-row label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    color: #c7c7c7;
    font-size: var(--ms-fs-subtitle);
  }

  .attribution-row select {
    min-width: 220px;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid #444;
    background: #1e1e1e;
    color: #ffffff;
  }

  .hitl-panel {
    margin-top: 14px;
  }

  .hitl-card {
    border: 1px solid #3b3b3b;
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 10px;
    background: #171717;
    text-align: left;
  }

  .hitl-card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .confidence {
    font-size: var(--ms-fs-meta);
    border-radius: 999px;
    padding: 2px 8px;
    border: 1px solid #4d4d4d;
    color: #d8d8d8;
  }

  .confidence.high {
    border-color: #2e7d32;
    color: #9be7a0;
  }

  .confidence.medium {
    border-color: #b28704;
    color: #f3d47a;
  }

  .confidence.low {
    border-color: #b33a3a;
    color: #ff9c9c;
  }

  .confidence.user-flagged {
    border-color: #7e4a00;
    color: #ffb347;
  }

  .flag-panel {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 6px;
    flex-wrap: wrap;
  }

  .flag-panel-label {
    font-size: var(--ms-fs-meta);
    color: #888;
  }

  .flag-list {
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
  }

  .flag-btn {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 1px solid #555;
    background: #2a2a2a;
    color: #aaa;
    font-size: 0.75rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    transition: background 0.15s, border-color 0.15s;
  }

  .flag-btn:hover {
    border-color: #ffb347;
    color: #ffb347;
  }

  .flag-btn.flagged {
    background: #7e4a00;
    border-color: #ffb347;
    color: #ffb347;
  }

  .hitl-bullet {
    margin: 0 0 8px;
    color: #f0f0f0;
    font-size: var(--ms-fs-body);
    line-height: var(--ms-line-body);
  }

  .hitl-bullet--remove {
    color: #e05c5c;
    font-style: italic;
    opacity: 0.85;
  }

  .remove-confirm-hint {
    margin: 0 0 10px;
    color: #e05c5c;
    font-size: var(--ms-fs-subtitle);
    font-style: italic;
  }

  .hitl-sources {
    margin: 0 0 8px;
    color: #c7c7c7;
    font-size: var(--ms-fs-subtitle);
  }

  .hitl-question {
    margin-top: 8px;
    color: #d8d8d8;
    font-size: var(--ms-fs-subtitle);
    line-height: var(--ms-line-body);
  }

  .hitl-actions {
    margin-top: 10px;
    display: flex;
    gap: 8px;
  }

  .conversation-panel {
    margin-top: 10px;
    border-top: 1px solid #3a3a3a;
    padding-top: 10px;
  }

  .conversation-panel h4 {
    margin: 0 0 8px;
    color: #ffffff;
    font-size: 0.98rem;
    font-weight: 600;
  }

  .confidence.user-flagged {
    border-color: #7e4a00;
    color: #ffb347;
  }

  .flag-mode-btn {
    font-size: var(--ms-fs-meta);
    padding: 3px 10px;
    border-radius: 6px;
    border: 1px solid #555;
    background: #2a2a2a;
    color: #aaa;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .flag-mode-btn:hover, .flag-mode-btn.active {
    border-color: #ffb347;
    color: #ffb347;
    background: #2e1f00;
  }

  .flag-list-view {
    background: #1e1e1e;
    border: 1px solid #333;
    border-radius: 12px;
    padding: 12px 14px;
    height: clamp(120px, 24vh, 280px);
    overflow-y: auto;
  }

  .flag-instruction {
    font-size: var(--ms-fs-meta);
    color: #888;
    margin: 0 0 8px;
  }

  .flag-bullets {
    list-style: decimal;
    padding-left: 1.4em;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .flag-bullet {
    color: #d0d0d0;
    font-size: var(--ms-fs-subtitle);
    line-height: var(--ms-line-body);
    padding: 4px 8px;
    border-radius: 6px;
    cursor: pointer;
    user-select: none;
    transition: background 0.12s;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }

  .flag-bullet:hover {
    background: #2a2a2a;
  }

  .flag-bullet.flagged {
    background: #2e1f00;
    color: #ffb347;
  }

  .flag-icon {
    font-size: 0.85rem;
    flex-shrink: 0;
  }

  .conversation-input textarea {
    width: 100%;
    min-height: 72px;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid #3a3a3a;
    background: #141414;
    color: #f0f0f0;
    box-sizing: border-box;
    resize: vertical;
    font-family: inherit;
    font-size: var(--ms-fs-body);
    line-height: var(--ms-line-body);
  }

  .summary-model-meta {
    margin: 4px 0 0;
    color: #a3a3a3;
    font-size: var(--ms-fs-meta);
  }

  :global(:root[data-theme='light']) h2,
  :global(:root[data-theme='light']) .attribution-controls h3,
  :global(:root[data-theme='light']) .conversation-panel h4 {
    color: #111827;
  }

  :global(:root[data-theme='light']) .attribution-toggle,
  :global(:root[data-theme='light']) .summary-toggle,
  :global(:root[data-theme='light']) .selected-line,
  :global(:root[data-theme='light']) .attribution-row label,
  :global(:root[data-theme='light']) .hitl-question,
  :global(:root[data-theme='light']) .hitl-sources,
  :global(:root[data-theme='light']) .flag-bullet,
  :global(:root[data-theme='light']) .summary-model-meta,
  :global(:root[data-theme='light']) .attendee-row,
  :global(:root[data-theme='light']) .attendee-label,
  :global(:root[data-theme='light']) .attendee-chip {
    color: #475569;
  }

  :global(:root[data-theme='light']) .hitl-card,
  :global(:root[data-theme='light']) .flag-list-view,
  :global(:root[data-theme='light']) .export-dropdown {
    background: #f8fafc;
    border-color: #d8e1eb;
  }

  :global(:root[data-theme='light']) .hitl-bullet {
    color: #0f172a;
  }

  :global(:root[data-theme='light']) .conversation-input textarea,
  :global(:root[data-theme='light']) .manual-speaker-add input,
  :global(:root[data-theme='light']) .attribution-row select,
  :global(:root[data-theme='light']) .export-dropdown button {
    background: #ffffff;
    border-color: #d8e1eb;
    color: #111827;
  }

  :global(:root[data-theme='light']) .flag-btn,
  :global(:root[data-theme='light']) .flag-mode-btn,
  :global(:root[data-theme='light']) .action-button {
    background: #f8fafc;
    border-color: #d8e1eb;
    color: #111827;
  }

  :global(:root[data-theme='light']) .flag-bullet:hover,
  :global(:root[data-theme='light']) .flag-btn:hover,
  :global(:root[data-theme='light']) .flag-mode-btn:hover,
  :global(:root[data-theme='light']) .flag-mode-btn.active,
  :global(:root[data-theme='light']) .action-button:hover {
    background: #e9eef5;
    border-color: #cfd9e5;
    color: #0f172a;
  }

  :global(:root[data-theme='light']) .flag-btn.flagged,
  :global(:root[data-theme='light']) .flag-bullet.flagged {
    background: #fef3c7;
    border-color: #f59e0b;
    color: #92400e;
  }

</style>

