const { createApp, ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } = Vue;

createApp({
  setup() {
    const loading = ref(true);
    const hasKey = ref(false);
    const showKeyForm = ref(false);
    const apiKeyInput = ref('');
    const keyError = ref(false);
    const keyMessage = ref('');
    const keyMessageClass = ref('');
    const savingKey = ref(false);

    const activeTab = ref('controls');
    const tabs = [
      { id: 'live', label: 'Live' },
      { id: 'controls', label: 'Controls' },
      { id: 'settings', label: 'Settings' },
      { id: 'personality', label: 'Personality' },
      { id: 'tools', label: 'Tools & Skills' },
      { id: 'logs', label: 'Logs' },
    ];

    const choices = ref([]);
    const selectedProfile = ref('');
    const startupProfile = ref('');
    const voices = ref(['cedar']);
    const settingsMessage = ref('');
    const settingsMessageClass = ref('');

    const profileName = ref('');
    const profileVoice = ref('cedar');
    const profileInstructions = ref('');
    const profileToolsText = ref('');
    const availableTools = ref([]);
    const enabledTools = reactive(new Set());
    const savingProfile = ref(false);
    const profileMessage = ref('');
    const profileMessageClass = ref('');

    // Computed: merge available + enabled so custom tools show up in grid
    const allTools = computed(() => {
      const merged = new Set([...availableTools.value, ...enabledTools]);
      return Array.from(merged).sort();
    });

    const registeredTools = ref([]);
    const AUTO_WITH = { dance: ['stop_dance'], play_emotion: ['stop_emotion'] };

    const logText = ref('');
    const logOutput = ref(null);
    const logMessages = ref(null);
    const autoRefreshLogs = ref(false);
    const parsedMessages = ref([]);
    let logInterval = null;

    // ---- Connection + Sleep/Wake state ----
    const robotConnected = ref(false);
    const robotAwake = ref(false);
    const sleepBusy = ref(false);
    let statusInterval = null;

    // ---- Controls tab state ----
    const DANCE_CATALOG = [
      { id: 'jackson_square', label: 'Jackson Square', desc: 'Precision shoulder pops with sharp hits' },
      { id: 'interwoven_spirals', label: 'Interwoven Spirals', desc: 'Layered, twisting spirals across axes' },
      { id: 'polyrhythm_combo', label: 'Polyrhythm Combo', desc: 'Offset waves and counter-beats' },
      { id: 'dizzy_spin', label: 'Dizzy Spin', desc: 'Slow antenna-flared spins' },
      { id: 'groovy_sway_and_roll', label: 'Groovy Sway & Roll', desc: 'Flowing torso rolls with side sways' },
      { id: 'pendulum_swing', label: 'Pendulum Swing', desc: 'Steady back-and-forth pendulum motion' },
      { id: 'side_to_side_sway', label: 'Side-to-Side Sway', desc: 'Energetic lateral grooves' },
      { id: 'grid_snap', label: 'Grid Snap', desc: 'Sharp, grid-aligned robotic accents' },
      { id: 'stumble_and_recover', label: 'Stumble & Recover', desc: 'Playful trip-and-reset sequence' },
      { id: 'chicken_peck', label: 'Chicken Peck', desc: 'Repetitive pecking head bops' },
      { id: 'chin_lead', label: 'Chin Lead', desc: 'Smooth, chin-guided glides' },
      { id: 'simple_nod', label: 'Simple Nod', desc: 'Continuous up-and-down nodding' },
      { id: 'head_tilt_roll', label: 'Head Tilt Roll', desc: 'Continuous side-to-side head roll' },
      { id: 'sharp_side_tilt', label: 'Sharp Side Tilt', desc: 'Quick side-to-side triangle tilt' },
      { id: 'side_peekaboo', label: 'Side Peekaboo', desc: 'Multi-stage hiding and peeking' },
      { id: 'neck_recoil', label: 'Neck Recoil', desc: 'Quick backward recoil' },
      { id: 'side_glance_flick', label: 'Side Glance Flick', desc: 'Quick glance to the side with snap' },
    ];
    const EMOTION_CATALOG = [
      { id: 'yeah_nod', label: 'Yeah Nod', emoji: '👍', desc: 'Enthusiastic up-down head bob' },
      { id: 'uh_huh_tilt', label: 'Uh-Huh Tilt', emoji: '😊', desc: 'Bouncy side-to-side affirm' },
      { id: 'simple_nod', label: 'Simple Nod', emoji: '✅', desc: 'Basic agreement dip' },
      { id: 'sharp_side_tilt', label: 'Sharp Side Tilt', emoji: '🙃', desc: 'Quick angular lean' },
      { id: 'side_glance_flick', label: 'Side Glance Flick', emoji: '👀', desc: 'Fast peek with snap' },
      { id: 'neck_recoil', label: 'Neck Recoil', emoji: '😲', desc: 'Snappy pop-back surprise' },
      { id: 'head_tilt_roll', label: 'Head Tilt Roll', emoji: '🤔', desc: 'Gentle looping curiosity' },
    ];
    const availableDances = ref(DANCE_CATALOG);
    const availableEmotions = ref(EMOTION_CATALOG);
    const controlBusy = ref(false);
    const controlMessage = ref('');
    const controlMessageClass = ref('');

    // ---- Live tab state ----
    const cameraStreamUrl = ref('/camera/stream');
    const cameraError = ref(false);
    const stylePrompt = ref('');
    const generatingImage = ref(false);
    const galleryImages = ref([]);
    const liveMessage = ref('');
    const liveMessageClass = ref('');
    const modalImage = ref(null);

    // ---- Helpers ----
    async function fetchJSON(url, opts = {}, timeoutMs = 5000) {
      const ctrl = new AbortController();
      const id = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const resp = await fetch(url, { ...opts, signal: ctrl.signal });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
      } finally { clearTimeout(id); }
    }

    async function poll(url, timeoutMs = 12000) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        try {
          const resp = await fetch(url, { signal: AbortSignal.timeout(2000) });
          if (resp.ok) return await resp.json();
        } catch {}
        await new Promise(r => setTimeout(r, 500));
      }
      return null;
    }

    // ---- Connection status polling ----
    async function checkRobotStatus() {
      try {
        const data = await fetchJSON(`/control/status?_=${Date.now()}`, {}, 3000);
        robotConnected.value = data.connected !== false;
        robotAwake.value = data.awake !== false;
      } catch {
        // If we can reach the server at all (status endpoint), mark as connected but unknown state
        try {
          await fetchJSON(`/status?_=${Date.now()}`, {}, 2000);
          robotConnected.value = true;
          // If /control/status doesn't exist yet, assume awake
          robotAwake.value = true;
        } catch {
          robotConnected.value = false;
          robotAwake.value = false;
        }
      }
    }

    function startStatusPolling() {
      checkRobotStatus();
      statusInterval = setInterval(checkRobotStatus, 5000);
    }

    // ---- Sleep / Wake ----
    async function toggleSleepWake() {
      sleepBusy.value = true;
      const action = robotAwake.value ? 'sleep' : 'wake';
      controlMessage.value = action === 'sleep' ? 'Putting Rosie to sleep...' : 'Waking Rosie up...';
      controlMessageClass.value = '';
      try {
        const data = await fetchJSON(`/control/${action}`, { method: 'POST' }, 10000);
        if (data.error) {
          controlMessage.value = data.error;
          controlMessageClass.value = 'msg-error';
        } else {
          robotAwake.value = action === 'wake';
          controlMessage.value = action === 'wake' ? 'Rosie is awake!' : 'Rosie is sleeping.';
          controlMessageClass.value = 'msg-ok';
        }
      } catch {
        controlMessage.value = `Failed to ${action} — is Rosie running?`;
        controlMessageClass.value = 'msg-error';
      } finally {
        sleepBusy.value = false;
        // Refresh status
        setTimeout(checkRobotStatus, 1000);
      }
    }

    // ---- API Key ----
    async function saveApiKey() {
      const key = apiKeyInput.value.trim();
      if (!key) { keyError.value = true; keyMessage.value = 'Enter a valid key.'; keyMessageClass.value = 'msg-warn'; return; }
      savingKey.value = true; keyMessage.value = 'Validating...'; keyMessageClass.value = '';
      try {
        const v = await fetchJSON('/validate_api_key', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ openai_api_key: key }) });
        if (!v.valid) { keyError.value = true; keyMessage.value = 'Invalid key.'; keyMessageClass.value = 'msg-error'; savingKey.value = false; return; }
        await fetchJSON('/openai_api_key', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ openai_api_key: key }) });
        keyMessage.value = 'Saved. Reloading...'; keyMessageClass.value = 'msg-ok';
        setTimeout(() => location.reload(), 800);
      } catch { keyError.value = true; keyMessage.value = 'Failed.'; keyMessageClass.value = 'msg-error'; }
      finally { savingKey.value = false; }
    }

    // ---- Profiles ----
    async function loadProfile() {
      const name = selectedProfile.value;
      if (!name) return;
      try {
        const data = await fetchJSON(`/personalities/load?name=${encodeURIComponent(name)}&_=${Date.now()}`);
        profileInstructions.value = data.instructions || '';
        profileToolsText.value = data.tools_text || '';
        profileVoice.value = data.voice || 'cedar';
        availableTools.value = data.available_tools || [];
        enabledTools.clear();
        (data.enabled_tools || []).forEach(t => enabledTools.add(t));
        const idx = name.lastIndexOf('/');
        profileName.value = idx >= 0 ? name.slice(idx + 1) : '';
        profileMessage.value = '';
      } catch { profileMessage.value = 'Failed to load.'; profileMessageClass.value = 'msg-error'; }
    }

    function toggleTool(name) {
      if (enabledTools.has(name)) { enabledTools.delete(name); }
      else { enabledTools.add(name); if (AUTO_WITH[name]) AUTO_WITH[name].forEach(d => enabledTools.add(d)); }
      syncToolsText();
    }

    function syncToolsText() {
      const comments = profileToolsText.value.split('\n').filter(ln => ln.trim().startsWith('#'));
      const body = Array.from(enabledTools).join('\n');
      profileToolsText.value = (comments.join('\n') + (comments.length ? '\n' : '') + body).trim() + '\n';
    }

    function newProfile() {
      profileName.value = ''; profileInstructions.value = ''; profileToolsText.value = '';
      profileVoice.value = 'cedar'; enabledTools.clear();
      profileMessage.value = 'Fill in fields and save.'; profileMessageClass.value = '';
    }

    async function saveProfile() {
      const name = profileName.value.trim();
      if (!name) { profileMessage.value = 'Enter a name.'; profileMessageClass.value = 'msg-warn'; return; }
      savingProfile.value = true; profileMessage.value = 'Saving...'; profileMessageClass.value = '';
      try {
        syncToolsText();
        const res = await fetchJSON('/personalities/save', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, instructions: profileInstructions.value, tools_text: profileToolsText.value, voice: profileVoice.value }),
        });
        if (res.choices) { choices.value = res.choices; if (res.value) selectedProfile.value = res.value; }
        profileMessage.value = 'Saved & applied.'; profileMessageClass.value = 'msg-ok';
        try { await fetchJSON(`/personalities/apply?name=${encodeURIComponent(selectedProfile.value)}&_=${Date.now()}`, { method: 'POST' }); } catch {}
      } catch { profileMessage.value = 'Save failed.'; profileMessageClass.value = 'msg-error'; }
      finally { savingProfile.value = false; }
    }

    async function applyProfile(persist) {
      const name = selectedProfile.value;
      settingsMessage.value = persist ? 'Setting startup...' : 'Applying...'; settingsMessageClass.value = '';
      try {
        const url = `/personalities/apply?name=${encodeURIComponent(name)}${persist ? '&persist=1' : ''}&_=${Date.now()}`;
        const res = await fetchJSON(url, { method: 'POST' });
        if (res.startup) startupProfile.value = res.startup;
        settingsMessage.value = res.status || (persist ? 'Set as startup.' : 'Applied.');
        settingsMessageClass.value = 'msg-ok';
      } catch { settingsMessage.value = 'Failed.'; settingsMessageClass.value = 'msg-error'; }
    }

    // ---- Tools ----
    async function fetchRegisteredTools() {
      try {
        const data = await fetchJSON(`/tools/list?_=${Date.now()}`);
        registeredTools.value = data.tools || [];
      } catch { registeredTools.value = []; }
    }

    // ---- Live: Gallery & Image Generation ----
    async function fetchGalleryImages() {
      try {
        const data = await fetchJSON(`/nanobanan/images?_=${Date.now()}`);
        galleryImages.value = data.images || [];
      } catch { galleryImages.value = []; }
    }

    async function takePhoto() {
      liveMessage.value = 'Capturing...'; liveMessageClass.value = '';
      generatingImage.value = true;
      try {
        const data = await fetchJSON('/camera/save', { method: 'POST' }, 10000);
        if (data.error) { liveMessage.value = data.error; liveMessageClass.value = 'msg-error'; }
        else { liveMessage.value = `Saved: ${data.filename}`; liveMessageClass.value = 'msg-ok'; fetchGalleryImages(); }
      } catch (e) { liveMessage.value = 'Capture failed.'; liveMessageClass.value = 'msg-error'; }
      finally { generatingImage.value = false; }
    }

    async function applyStyle() {
      const prompt = stylePrompt.value.trim();
      if (!prompt) return;
      liveMessage.value = 'Generating with Nano Banana...'; liveMessageClass.value = '';
      generatingImage.value = true;
      try {
        const data = await fetchJSON('/nanobanan/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, source_image: 'camera' }),
        }, 60000);
        if (data.error) { liveMessage.value = data.error; liveMessageClass.value = 'msg-error'; }
        else { liveMessage.value = `Created: ${data.filename}`; liveMessageClass.value = 'msg-ok'; fetchGalleryImages(); }
      } catch { liveMessage.value = 'Generation failed.'; liveMessageClass.value = 'msg-error'; }
      finally { generatingImage.value = false; }
    }

    function openImage(img) { modalImage.value = img; }

    // ---- Controls: Dance, Emotion, Session ----
    async function fetchDances() {
      try {
        const data = await fetchJSON(`/control/dances?_=${Date.now()}`);
        if (data.moves && data.moves.length) {
          const catalogMap = Object.fromEntries(DANCE_CATALOG.map(d => [d.id, d]));
          availableDances.value = data.moves.map(id => catalogMap[id] || { id, label: id.replace(/_/g, ' '), desc: '' });
        }
      } catch { /* keep catalog defaults */ }
    }

    async function fetchEmotions() {
      try {
        const data = await fetchJSON(`/control/emotions?_=${Date.now()}`);
        if (data.emotions && data.emotions.length) {
          const catalogMap = Object.fromEntries(EMOTION_CATALOG.map(e => [e.id, e]));
          availableEmotions.value = data.emotions.map(e => {
            const name = e.name || e;
            const cat = catalogMap[name];
            return cat || { id: name, label: name.replace(/_/g, ' '), emoji: '', desc: e.description || '' };
          });
        }
      } catch { /* keep catalog defaults */ }
    }

    async function triggerDance(dance) {
      controlBusy.value = true;
      controlMessage.value = `Dancing: ${dance.label}...`;
      controlMessageClass.value = '';
      try {
        const data = await fetchJSON('/control/dance', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ move: dance.id, repeat: 1 }),
        });
        controlMessage.value = data.error ? data.error : `Queued: ${dance.label}`;
        controlMessageClass.value = data.error ? 'msg-error' : 'msg-ok';
      } catch { controlMessage.value = 'Dance failed — is Rosie running?'; controlMessageClass.value = 'msg-error'; }
      finally { controlBusy.value = false; }
    }

    async function triggerEmotion(emotion) {
      controlBusy.value = true;
      controlMessage.value = `Playing: ${emotion.label}...`;
      controlMessageClass.value = '';
      try {
        const data = await fetchJSON('/control/emotion', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ emotion: emotion.id }),
        });
        controlMessage.value = data.error ? data.error : `Queued: ${emotion.label}`;
        controlMessageClass.value = data.error ? 'msg-error' : 'msg-ok';
      } catch { controlMessage.value = 'Emotion failed — is Rosie running?'; controlMessageClass.value = 'msg-error'; }
      finally { controlBusy.value = false; }
    }

    async function stopAll() {
      controlBusy.value = true;
      controlMessage.value = 'Stopping...';
      try {
        await fetchJSON('/control/stop', { method: 'POST' });
        controlMessage.value = 'Stopped all movement.';
        controlMessageClass.value = 'msg-ok';
      } catch { controlMessage.value = 'Stop failed.'; controlMessageClass.value = 'msg-error'; }
      finally { controlBusy.value = false; }
    }

    async function restartSession() {
      controlBusy.value = true;
      controlMessage.value = 'Restarting voice session...';
      controlMessageClass.value = '';
      try {
        const data = await fetchJSON('/control/restart', { method: 'POST' }, 15000);
        controlMessage.value = data.error ? data.error : 'Voice session restarted!';
        controlMessageClass.value = data.error ? 'msg-error' : 'msg-ok';
      } catch { controlMessage.value = 'Restart failed — is Rosie running?'; controlMessageClass.value = 'msg-error'; }
      finally { controlBusy.value = false; }
    }

    // ---- Logs ----
    function parseLogMessages(raw) {
      const messages = [];
      const lines = raw.split('\n');
      for (const line of lines) {
        const toolMatch = line.match(/Tool call: (\w+)\s+(.*)/);
        if (toolMatch) {
          const time = line.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || '';
          messages.push({ type: 'tool', role: 'tool', time, text: `${toolMatch[1]}: ${toolMatch[2]}` });
          continue;
        }
        const contentMatch = line.match(/role=(\w+)\s+content=(.*)/);
        if (contentMatch) {
          const time = line.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || '';
          const role = contentMatch[1];
          let text = contentMatch[2];
          try {
            const parsed = JSON.parse(text);
            if (parsed.status) text = `[${parsed.status}] ${parsed.reason || parsed.move || parsed.emotion || parsed.message || ''}`.trim();
            else if (parsed.image_description) text = `[camera] ${parsed.image_description}`;
            else text = JSON.stringify(parsed, null, 2);
          } catch {}
          const type = role === 'assistant' ? 'assistant' : role === 'user' ? 'user' : 'system';
          messages.push({ type, role, time, text });
          continue;
        }
        const speechMatch = line.match(/transcript.*?['"](.*?)['"]/i) || line.match(/user.*?said.*?['"](.*?)['"]/i);
        if (speechMatch) {
          const time = line.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || '';
          messages.push({ type: 'user', role: 'user', time, text: speechMatch[1] });
          continue;
        }
        if (line.includes('Realtime session') || line.includes('Loading prompt') || line.includes('Starting Reachy')) {
          const time = line.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || '';
          const text = line.replace(/.*INFO\s+\S+\s*\|\s*/, '').replace(/.*INFO:.*?\|\s*/, '').trim();
          if (text) messages.push({ type: 'system', role: 'system', time, text });
        }
      }
      return messages;
    }

    async function fetchLogs() {
      try {
        const data = await fetchJSON(`/logs?lines=300&_=${Date.now()}`);
        logText.value = data.logs || 'No logs.';
        parsedMessages.value = parseLogMessages(data.logs || '');
        await nextTick();
        if (logMessages.value) logMessages.value.scrollTop = logMessages.value.scrollHeight;
        if (logOutput.value) logOutput.value.scrollTop = logOutput.value.scrollHeight;
      } catch { logText.value = 'Error fetching logs.'; }
    }

    function toggleLogRefresh() {
      if (autoRefreshLogs.value) { fetchLogs(); logInterval = setInterval(fetchLogs, 3000); }
      else { if (logInterval) { clearInterval(logInterval); logInterval = null; } }
    }

    watch(activeTab, (tab) => {
      if (tab === 'logs') fetchLogs();
      if (tab === 'tools') fetchRegisteredTools();
      if (tab === 'live') fetchGalleryImages();
      if (tab === 'controls') { fetchDances(); fetchEmotions(); }
    });

    onMounted(async () => {
      const st = await poll('/status');
      hasKey.value = st?.has_key || false;
      showKeyForm.value = !hasKey.value;
      if (hasKey.value) {
        const list = await poll('/personalities');
        if (list?.choices) {
          choices.value = list.choices;
          startupProfile.value = list.startup || list.choices[0] || '';
          selectedProfile.value = list.current || startupProfile.value || list.choices[0] || '';
        }
        try { const v = await fetchJSON(`/voices?_=${Date.now()}`); if (Array.isArray(v) && v.length) voices.value = v; } catch {}
        if (selectedProfile.value) await loadProfile();
        fetchRegisteredTools();
      }
      fetchGalleryImages();
      // Start polling robot connection status
      startStatusPolling();
      // Load controls data
      fetchDances();
      fetchEmotions();
      loading.value = false;
    });

    onUnmounted(() => {
      if (logInterval) clearInterval(logInterval);
      if (statusInterval) clearInterval(statusInterval);
    });

    return {
      loading, hasKey, showKeyForm, apiKeyInput, keyError, keyMessage, keyMessageClass, savingKey, saveApiKey,
      activeTab, tabs,
      choices, selectedProfile, startupProfile, voices, settingsMessage, settingsMessageClass,
      profileName, profileVoice, profileInstructions, profileToolsText,
      availableTools, enabledTools, allTools, savingProfile, profileMessage, profileMessageClass,
      loadProfile, toggleTool, newProfile, saveProfile, applyProfile,
      registeredTools,
      logText, logOutput, logMessages, autoRefreshLogs, parsedMessages, fetchLogs, toggleLogRefresh,
      // Connection + sleep/wake
      robotConnected, robotAwake, sleepBusy, toggleSleepWake,
      // Controls tab
      availableDances, availableEmotions, controlBusy, controlMessage, controlMessageClass,
      triggerDance, triggerEmotion, stopAll, restartSession,
      // Live tab
      cameraStreamUrl, cameraError, stylePrompt, generatingImage,
      galleryImages, liveMessage, liveMessageClass, modalImage,
      takePhoto, applyStyle, fetchGalleryImages, openImage,
    };
  },
}).mount('#app');
