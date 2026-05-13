<script>
  import { getWSURL, getAPIBaseURL } from '../lib/config.js';
  let ws;
  let transcript = "";
  let bullets = "";
  let recording = false;
  let mediaRecorder;
  let audioChunks = [];

  async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    ws = new WebSocket(getWSURL('ws/live-transcribe'));
    ws.binaryType = "arraybuffer";

    ws.onmessage = (event) => {
      transcript = event.data;
    };

    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
      // Send last chunk
      for (const chunk of audioChunks) {
        ws.send(await chunk.arrayBuffer());
      }
    };

    mediaRecorder.start(1000); // capture every 1s

    recording = true;
    sendAudioLoop();
  }

  async function sendAudioLoop() {
    if (!recording) return;
    if (mediaRecorder && mediaRecorder.state === "recording" && audioChunks.length > 0) {
      const chunk = audioChunks.shift();
      ws.send(await chunk.arrayBuffer());
    }
    setTimeout(sendAudioLoop, 200);
  }

  function stopRecording() {
    recording = false;
    if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
  }

  async function summarizeMeeting() {
    const res = await fetch(`${getAPIBaseURL()}/summarize-meeting`, {
      method: "POST"
    });
    const data = await res.json();
    bullets = data.bullets;
  }

  function toggleRecording() {
    if (!recording) startRecording();
    else stopRecording();
  }
</script>

<button on:click={toggleRecording}>
  {recording ? "Stop Meeting" : "Start Meeting"}
</button>

<button on:click={summarizeMeeting}>Summarize Meeting</button>

<h3>Transcript</h3>
<p>{transcript}</p>

<h3>Bullet Summary</h3>
<pre>{bullets}</pre>
