const element = id => document.getElementById(id);
const form = element('upload-form');
const fields = element('upload-fields');
const status = element('status');
const remove = element('delete');
const limits = { bytes: 25 * 1024 * 1024, seconds: 60 };
const videoTypes = new Map([['mp4', 'video/mp4'], ['mov', 'video/quicktime'], ['webm', 'video/webm']]);
let session;
let pollTimer;

const videoInput = element('video');
const clipSelection = element('clip-selection');
const analyzeSubmit = element('analyze-submit');
const videoActions = element('video-actions');

function updateClipSelection() {
  const clip = videoInput.files[0];
  clipSelection.textContent = clip ? clip.name : 'No clip selected';
  analyzeSubmit.disabled = !clip;
}

element('record-video').addEventListener('click', () => {
  videoInput.setAttribute('capture', 'environment');
  videoInput.click();
});
element('choose-video').addEventListener('click', () => {
  videoInput.removeAttribute('capture');
  videoInput.click();
});
videoInput.addEventListener('change', updateClipSelection);

function clipDuration(file) {
  return new Promise(resolve => {
    const video = document.createElement('video');
    const url = URL.createObjectURL(file);
    const timer = setTimeout(() => finish(null), 3000);

    function finish(duration) {
      clearTimeout(timer);
      video.onloadedmetadata = video.onerror = null;
      video.removeAttribute('src');
      video.load();
      URL.revokeObjectURL(url);
      resolve(duration);
    }

    video.preload = 'metadata';
    video.onloadedmetadata = () => finish(video.duration);
    video.onerror = () => finish(null);
    video.src = url;
  });
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, cache: 'no-store' });
  if (response.ok || (options.method === 'DELETE' && response.status === 404)) return response;
  if (response.status === 401) throw Object.assign(Error('Sign in with your pilot credentials and try again.'), { status: 401 });
  if (response.status === 413) throw Error('Choose a video up to 25 MB.');
  if (response.status === 415) throw Error('Choose a playable MP4, MOV or WebM clip.');
  if (response.status === 404) throw Object.assign(Error('This session is no longer available.'), { status: 404 });
  throw Error('The server couldn’t complete the request. Try again.');
}

function sessionRequest(method, suffix = '', body) {
  return request('/api/sessions/' + session.session_id + suffix, {
    method, body, headers: { 'X-Session-Token': session.session_token },
  });
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (fields.disabled || session) return;

  const file = element('video').files[0];
  const extension = file?.name.split('.').pop().toLowerCase();
  const mime = videoTypes.get(extension);
  if (!mime) {
    status.textContent = 'Choose an MP4, MOV or WebM clip.';
    return;
  }
  if (!file.size || file.size > limits.bytes) {
    status.textContent = 'Choose a nonempty clip up to 25 MB.';
    return;
  }

  fields.disabled = true;
  videoActions.hidden = true;
  status.textContent = 'Checking video…';
  try {
    const duration = await clipDuration(file);
    if (Number.isFinite(duration) && duration > limits.seconds) {
      throw Error(`Trim this clip to ${limits.seconds} seconds or less in Photos, then choose it again.`);
    }
    status.textContent = 'Uploading video…';
    const created = await request('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        station_id: new URLSearchParams(location.search).get('station') || 'demo-station',
        consent: element('consent').checked,
        lead_arm: element('lead-arm').value,
      }),
    });
    session = await created.json();
    const body = new FormData();
    body.append('video', file.slice(0, file.size, mime), 'clip.' + extension);
    await sessionRequest('POST', '/video', body);
    status.textContent = 'Video uploaded. Waiting for analysis…';
    await checkStatus();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    remove.hidden = !session;
    fields.disabled = Boolean(session);
    form.hidden = Boolean(session);
    videoActions.hidden = Boolean(session);
  }
});

function showResult(result) {
  if (result.analysis_type !== 'experimental_pose_extension_v1') {
    status.textContent = 'Video received. The server’s pose analysis is disabled.';
    return;
  }
  element('tip').textContent = result.experimental_feedback || 'A filming suggestion is temporarily unavailable.';
  const source = result.feedback_backend === 'vllm' ? 'AI-selected tip' : 'Built-in pilot feedback';
  element('source').textContent = result.experimental_feedback ? source + ' · Experimental' : '';
  const coverage = Math.round(result.usable_frame_fraction * 100);
  const cycles = result.extension_cycle_candidates === null
    ? 'Visibility was too low to estimate movement cycles.'
    : result.extension_cycle_candidates + ' candidate arm extension and return cycles.';
  element('observations').textContent = [
    coverage + '% of sampled frames had usable lead-arm landmarks.',
    cycles,
    'Tracking estimates require coach review for technique assessment.',
  ].join('\n');
  element('result').hidden = false;
  status.textContent = 'Analysis complete. You can delete the video and session below.';
  element('result-title').focus();
}

async function checkStatus() {
  const current = session;
  if (!current) return;
  try {
    const response = await sessionRequest('GET');
    const job = await response.json();
    if (session !== current) return;
    if (job.status === 'completed') {
      showResult(job.result ?? {});
      return;
    }
    if (job.status === 'failed') {
      status.textContent = `Analysis failed. Delete this session and try another playable clip up to ${limits.seconds} seconds.`;
      return;
    }
    status.textContent = job.status === 'processing' ? 'Analyzing your video…' :
      job.result ? 'Analysis will retry shortly…' : 'Video uploaded. Waiting for analysis…';
  } catch (error) {
    if (session !== current) return;
    if (error.status === 401 || error.status === 404) {
      status.textContent = error.message;
      return;
    }
    status.textContent = error.message + ' Checking again shortly…';
  }
  pollTimer = setTimeout(checkStatus, 2000);
}

remove.addEventListener('click', async () => {
  remove.disabled = true;
  try {
    await sessionRequest('DELETE');
    clearTimeout(pollTimer);
    session = undefined;
    form.reset();
    updateClipSelection();
    videoActions.hidden = false;
    remove.hidden = element('result').hidden = true;
    form.hidden = fields.disabled = false;
    status.textContent = 'Session deleted. Choose another clip whenever you’re ready.';
  } catch {
    status.textContent = 'Couldn’t delete this session. Try again.';
  } finally {
    remove.disabled = false;
  }
});
