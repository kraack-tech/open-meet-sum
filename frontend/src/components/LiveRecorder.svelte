<script>
  import { getAPIBaseURL } from '../lib/config.js';
  
  let mediaRecorder;
  let audioChunks = [];
  let recording = false;
  let transcript = "";
  let bullets = "";

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  // Use Opus codec with lower bitrate to reduce file size
  mediaRecorder = new MediaRecorder(stream, { 
    mimeType: "audio/webm;codecs=opus",
    audioBitsPerSecond: 32000  // adjust bitrate for smaller files
  });
  audioChunks = [];

  mediaRecorder.ondataavailable = e => {
    if (e.data.size > 0) audioChunks.push(e.data);
  };

  mediaRecorder.start();
  recording = true;
}

function stopRecording() {
  if (!recording) return;
  mediaRecorder.stop();
  recording = false;

  mediaRecorder.onstop = async () => {
    // Blob and File use same Opus codec, optionally rename to .ogg
    const blob = new Blob(audioChunks, { type: "audio/webm;codecs=opus" });
    const file = new File([blob], "meeting.webm", { type: "audio/webm;codecs=opus" });

      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch(`${getAPIBaseURL()}/record-meeting`, {
          method: "POST",
          body: formData
        });
        const data = await res.json();
        transcript = data.transcript;
        bullets = data.bullets;
      } catch (err) {
        console.error(err);
      }
    };
  }
</script>

<button on:click={recording ? stopRecording : startRecording}>
  {recording ? "Stop Meeting" : "Start Meeting"}
</button>

<h3>Transcript</h3>
<p>{transcript}</p>

<h3>Bullet Summary</h3>
<pre>{bullets}</pre>
