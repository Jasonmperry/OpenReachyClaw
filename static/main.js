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

    const activeTab = ref('live');
    const tabs = [
      { id: 'live', label: 'Live' },
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

    // ---- Logs ----
    function parseLogMessages(raw) {
      const messages = [];
      const lines = raw.split('\n');
      for (const line of lines) {
        // Tool calls
        const toolMatch = line.match(/Tool call: (\w+)\s+(.*)/);
        if (toolMatch) {
          const time = line.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || '';
          messages.push({ type: 'tool', role: 'tool', time, text: `${toolMatch[1]}: ${toolMatch[2]}` });
          continue;
        }
        // Assistant content (conversation messages)
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
        // User speech (transcript)
        const speechMatch = line.match(/transcript.*?['"](.*?)['"]/i) || line.match(/user.*?said.*?['"](.*?)['"]/i);
        if (speechMatch) {
          const time = line.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || '';
          messages.push({ type: 'user', role: 'user', time, text: speechMatch[1] });
          continue;
        }
        // Realtime session events
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
      // Load gallery images on startup
      fetchGalleryImages();
      loading.value = false;
    });

    onUnmounted(() => { if (logInterval) clearInterval(logInterval); });

    return {
      loading, hasKey, showKeyForm, apiKeyInput, keyError, keyMessage, keyMessageClass, savingKey, saveApiKey,
      activeTab, tabs,
      choices, selectedProfile, startupProfile, voices, settingsMessage, settingsMessageClass,
      profileName, profileVoice, profileInstructions, profileToolsText,
      availableTools, enabledTools, allTools, savingProfile, profileMessage, profileMessageClass,
      loadProfile, toggleTool, newProfile, saveProfile, applyProfile,
      registeredTools,
      logText, logOutput, logMessages, autoRefreshLogs, parsedMessages, fetchLogs, toggleLogRefresh,
      // Live tab
      cameraStreamUrl, cameraError, stylePrompt, generatingImage,
      galleryImages, liveMessage, liveMessageClass, modalImage,
      takePhoto, applyStyle, fetchGalleryImages, openImage,
    };
  },
}).mount('#app');
