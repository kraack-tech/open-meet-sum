<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';
  import { getAPIBaseURL } from '../lib/config.js';

  export let enrollmentFinalized = false;
  export let attendees: string[] = [];
  export let historicalView = false;
  export let historicalAttendees: string[] = [];

  type SpeakerStatus = 'idle' | 'recording' | 'enrolled' | 'error';
  type DraftSpeaker = { name: string; status: SpeakerStatus };

  const dispatch = createEventDispatcher<{
    attendeesFinalized: { attendees: string[] };
    attendeesChanged: { attendees: string[] };
  }>();

  let speakerName = '';
  let speakers: DraftSpeaker[] = [];
  let existingSpeakers: string[] = [];
  let existingSearch = '';
  let selectedExisting: string[] = [];
  let attendeesFinalized = false;
  let existingLoading = false;

  let audioContext: AudioContext | null = null;
  let processor: ScriptProcessorNode | null = null;
  let buffer: Float32Array[] = [];
  let stream: MediaStream | null = null;

  const MAX_SAMPLE_MS = 8000;
  const MIN_SAMPLE_MS = 1500;
  const SILENCE_MS = 900;
  const SILENCE_THRESHOLD = 0.015;
  const ENROLLMENT_SCRIPT =
    'The quick brown fox jumps over the lazy dog, and I will join the meeting on time.';

  const API_BASE = getAPIBaseURL();

  let recordingStart = 0;
  let lastVoice = 0;
  let isStopping = false;
  let stopTimeout: any;

  onMount(() => {
    void loadExistingSpeakers();
  });

  async function loadExistingSpeakers() {
    existingLoading = true;
    const token = localStorage.getItem('meetsum_token') || '';
    try {
      const res = await fetch(`${API_BASE}/speakers`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) {
        existingSpeakers = [];
        return;
      }
      const payload = await res.json();
      const names = Array.isArray(payload?.items)
        ? payload.items.map((item: any) => String(item?.name || '').trim()).filter(Boolean)
        : [];
      existingSpeakers = Array.from(new Set(names));
    } catch {
      existingSpeakers = [];
    } finally {
      existingLoading = false;
    }
  }

  function addSpeaker() {
    if (enrollmentFinalized) return;
    const name = speakerName.trim();
    if (!name) return;
    if (speakers.some((s) => s.name.toLowerCase() === name.toLowerCase())) {
      speakerName = '';
      return;
    }
    speakers = [...speakers, { name, status: 'idle' }];
    speakerName = '';
    emitDraftAttendees();
  }

  function addExistingSpeaker(name: string) {
    if (attendeesFinalized) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    if (selectedExisting.some((s) => s.toLowerCase() === trimmed.toLowerCase())) return;
    selectedExisting = [...selectedExisting, trimmed];
    emitDraftAttendees();
  }

  function removeExistingSpeaker(name: string) {
    if (attendeesFinalized) return;
    selectedExisting = selectedExisting.filter((item) => item !== name);
    emitDraftAttendees();
  }

  function emitDraftAttendees() {
    const localSpeakerNames = speakers.map((speaker) => speaker.name.trim()).filter(Boolean);
    const picked = [...selectedExisting, ...localSpeakerNames];
    const draftAttendees = Array.from(new Set(picked));
    attendees = draftAttendees;
    dispatch('attendeesChanged', { attendees: draftAttendees });
  }

  async function recordSample(name: string) {
    if (enrollmentFinalized) return;
    const index = speakers.findIndex((s) => s.name === name);
    if (index === -1 || speakers[index].status === 'recording') return;

    speakers[index] = { ...speakers[index], status: 'recording' };
    speakers = [...speakers];

    buffer = [];
    recordingStart = performance.now();
    lastVoice = recordingStart;
    isStopping = false;

    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);

    source.connect(processor);
    processor.connect(audioContext.destination);

    processor.onaudioprocess = (e) => {
      const chunk = e.inputBuffer.getChannelData(0).slice();
      buffer.push(chunk);

      const rms = Math.sqrt(chunk.reduce((acc, s) => acc + s * s, 0) / chunk.length);
      if (rms > SILENCE_THRESHOLD) {
        lastVoice = performance.now();
      }

      const now = performance.now();
      if (now - recordingStart > MIN_SAMPLE_MS && now - lastVoice > SILENCE_MS) {
        stopSample(name);
      }
    };

    stopTimeout = setTimeout(() => stopSample(name), MAX_SAMPLE_MS);
  }

  async function stopSample(name: string) {
    if (isStopping || !audioContext || !processor) return;
    isStopping = true;

    if (stopTimeout) {
      clearTimeout(stopTimeout);
      stopTimeout = null;
    }

    processor.disconnect();
    await audioContext.close();
    if (stream) stream.getTracks().forEach((t) => t.stop());

    const flat = new Float32Array(buffer.reduce((acc, cur) => acc + cur.length, 0));
    let offset = 0;
    for (let b of buffer) {
      flat.set(b, offset);
      offset += b.length;
    }
    buffer = [];

    const wavBlob = encodeWAV(flat, audioContext.sampleRate);
    const file = new File([wavBlob], `${name}.wav`, { type: 'audio/wav' });

    const formData = new FormData();
    formData.append('name', name);
    formData.append('file', file);

    try {
      const token = localStorage.getItem('meetsum_token') || '';
      const res = await fetch(`${getAPIBaseURL()}/speakers/enroll`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: formData,
      });
      if (!res.ok) throw new Error('Enroll failed');

      updateSpeakerStatus(name, 'enrolled');
    } catch (err) {
      console.error(err);
      updateSpeakerStatus(name, 'error');
    }
  }

  function updateSpeakerStatus(name: string, status: 'idle' | 'recording' | 'enrolled' | 'error') {
    const index = speakers.findIndex((s) => s.name === name);
    if (index === -1) return;
    speakers[index] = { ...speakers[index], status };
    speakers = [...speakers];
  }

  function finalizeAttendees() {
    const localSpeakerNames = speakers.map((speaker) => speaker.name.trim()).filter(Boolean);
    const picked = [...selectedExisting, ...localSpeakerNames];
    attendees = Array.from(new Set(picked));
    attendeesFinalized = true;
    existingSearch = '';
    dispatch('attendeesChanged', { attendees });
    dispatch('attendeesFinalized', { attendees });
  }

  function finalizeEnrollment() {
    if (!attendeesFinalized) {
      finalizeAttendees();
    }
    enrollmentFinalized = true;
  }

  $: filteredExisting = existingSearch.trim()
    ? existingSpeakers.filter((name) => name.toLowerCase().includes(existingSearch.trim().toLowerCase()))
    : existingSpeakers;

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
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }

    return new Blob([view], { type: 'audio/wav' });
  }

  function writeString(view: DataView, offset: number, str: string) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  }
</script>

<div class="enroll">
  <section class="enroll-section">
    <h3>Meeting attendees</h3>
    {#if historicalView}
      <p class="attendee-summary">
        <strong>Attendees:</strong>
        {historicalAttendees.length ? historicalAttendees.join(', ') : 'No attendees registered.'}
      </p>
    {:else if attendeesFinalized}
      <p class="attendee-summary">
        <strong>Attendees:</strong>
        {attendees.join(', ')}
      </p>
    {:else}
      <div class="row">
        <input placeholder="Search speakers" bind:value={existingSearch} disabled={attendeesFinalized} />
        <button class="finish-btn" on:click={finalizeAttendees} disabled={attendeesFinalized}>Finish Attendees</button>
      </div>
      {#if existingLoading}
        <p class="script">Loading saved speakers...</p>
      {:else if filteredExisting.length}
        <div class="chips">
          {#each filteredExisting as name}
            <button type="button" class="chip" on:click={() => addExistingSpeaker(name)} disabled={attendeesFinalized || selectedExisting.includes(name)}>
              {name}
            </button>
          {/each}
        </div>
      {:else}
        <p class="script">No saved speakers found.</p>
      {/if}

      {#if selectedExisting.length}
        <div class="picked-list">
          <strong>Selected attendees:</strong>
          {#each selectedExisting as selected}
            <button type="button" class="picked" on:click={() => removeExistingSpeaker(selected)}>{selected} ×</button>
          {/each}
        </div>
      {/if}
    {/if}
  </section>

  {#if !historicalView && !attendeesFinalized}
    <details class="enroll-section enrollment-dropdown">
      <summary>Speaker enrollments</summary>
      {#if !enrollmentFinalized}
        <p class="script">Say this sentence clearly for best recognition:</p>
        <p class="script-text">"{ENROLLMENT_SCRIPT}"</p>
        <div class="row">
          <input placeholder="Name" bind:value={speakerName} />
          <button on:click={addSpeaker}>Add</button>
          <button class="finish-btn" on:click={finalizeEnrollment}>Finish Enrollment</button>
        </div>
      {:else}
        <p class="script finalized-note">Enrollment finalized. Speaker list is now read-only.</p>
      {/if}

      {#if speakers.length}
        <div class="list">
          {#each speakers as speaker}
            <div class="item">
              <span>{speaker.name}</span>
              {#if !enrollmentFinalized}
                <button on:click={() => recordSample(speaker.name)} disabled={speaker.status === 'recording'}>
                  {speaker.status === 'recording' ? 'Recording...' : 'Record sample (8s)'}
                </button>
              {/if}
              <span class="status {speaker.status}">{speaker.status}</span>
            </div>
          {/each}
        </div>
      {/if}
    </details>
  {/if}
</div>

<style>
  .enroll {
    width: 100%;
    max-width: calc(var(--ms-content-max-width) - 48px);
    margin: 0 auto 24px;
    padding: 16px 24px;
    border: 1px solid #333;
    border-radius: 12px;
    background: #1e1e1e;
    box-sizing: border-box;
  }

  .enroll-section + .enroll-section {
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid #2f2f2f;
  }

  .enroll-section h3 {
    margin: 0 0 10px;
  }

  .enrollment-dropdown summary {
    cursor: pointer;
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0;
  }

  .enrollment-dropdown[open] summary {
    margin-bottom: 10px;
  }

  .row {
    display: flex;
    gap: 12px;
    justify-content: center;
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 8px;
  }

  .chip {
    border: 1px solid #3a3a3a;
    background: #1a1a1a;
    color: #e6e6e6;
    border-radius: 999px;
    padding: 4px 10px;
    cursor: pointer;
  }

  .chip:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .picked-list {
    margin-top: 10px;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }

  .picked {
    border: 1px solid #3a3a3a;
    border-radius: 999px;
    background: #1f1f1f;
    color: #f0f0f0;
    padding: 4px 10px;
    cursor: pointer;
  }

  .picked.static {
    cursor: default;
  }

  .script {
    margin: 8px 0 4px;
    color: #c7c7c7;
    font-size: 0.95rem;
  }

  .attendee-summary {
    margin: 6px 0 0;
    color: #f0f0f0;
  }

  .finalized-note {
    margin-bottom: 8px;
  }

  .script-text {
    margin: 0 0 12px;
    color: #ffffff;
    font-style: italic;
  }

  input {
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid #333;
    background: #0f0f0f;
    color: #fff;
    min-width: 220px;
  }

  .finish-btn {
    border: 1px solid #3a3a3a;
  }

  .list {
    margin-top: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .status {
    font-size: 0.85rem;
    text-transform: capitalize;
  }

  .status.enrolled {
    color: #6ee7b7;
  }

  .status.error {
    color: #fca5a5;
  }

  :global(:root[data-theme='light']) .enroll {
    background: #ffffff;
    border-color: #d6d9df;
  }

  :global(:root[data-theme='light']) .enroll-section + .enroll-section {
    border-top-color: #e2e8f0;
  }

  :global(:root[data-theme='light']) .enroll-section h3,
  :global(:root[data-theme='light']) .enrollment-dropdown summary,
  :global(:root[data-theme='light']) .script-text,
  :global(:root[data-theme='light']) .attendee-summary {
    color: #111827;
  }

  :global(:root[data-theme='light']) .script {
    color: #475569;
  }

  :global(:root[data-theme='light']) input,
  :global(:root[data-theme='light']) .chip,
  :global(:root[data-theme='light']) .picked,
  :global(:root[data-theme='light']) .finish-btn {
    background: #ffffff;
    border-color: #d6d9df;
    color: #111827;
  }

  :global(:root[data-theme='light']) .chip:hover,
  :global(:root[data-theme='light']) .picked:hover,
  :global(:root[data-theme='light']) .finish-btn:hover {
    background: #eef2f7;
    border-color: #cbd5e1;
  }
</style>
