<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPanel from './AdminPanel.svelte';
  import LiveTranscriber from './LiveTranscriber.svelte';
  import SpeakerEnrollment from './SpeakerEnrollment.svelte';
  import UploadedAudio from './upload-audio.svelte';
  import { writable } from 'svelte/store';
  import { tick } from 'svelte';
  import { getAPIBaseURL, getWSURL } from '../lib/config.js';

  type AppMode = 'none' | 'meeting' | 'record' | 'upload' | 'chat' | 'settings' | 'admin' | 'account';
  type AppUser = {
    id: string;
    email: string;
    username?: string;
    display_name?: string;
    is_superuser?: boolean;
    is_active?: boolean;
  };
  type AppSettings = {
    theme: 'dark' | 'light';
    language: string;
    spokenLanguage: string;
    accountLabelMode: 'auto' | 'display_name' | 'username' | 'email';
  };
  type ChatMessage = {
    id: string;
    role: string;
    content: string;
    created_at?: string;
    pending?: boolean;
    error?: boolean;
  };
  type ActionCard = {
    type: string;
    label: string;
    payload?: Record<string, any>;
  };
  const SIDEBAR_LABEL_ACTION_TYPES = [
    'set_sidebar_label_auto',
    'set_sidebar_label_display_name',
    'set_sidebar_label_username',
    'set_sidebar_label_email',
  ];
  const THEME_ACTION_TYPES = ['set_theme_light', 'set_theme_dark'];
  const LANGUAGE_ACTION_TYPES = ['set_language_en', 'set_spoken_language'];
  const CAPABILITY_FALLBACK_ACTIONS: ActionCard[] = [
    { type: 'start_meeting', label: 'Start a live meeting' },
    { type: 'upload_meeting', label: 'Upload a meeting recording' },
    { type: 'start_speaker_enrollment', label: 'Start speaker enrollment' },
    { type: 'chat_general_mode', label: 'Switch to general chat mode' },
    { type: 'open_settings', label: 'Open user settings' },
    { type: 'set_theme_light', label: 'Set theme to Light' },
    { type: 'set_theme_dark', label: 'Set theme to Dark' },
    { type: 'set_language_en', label: 'Set app language to English' },
    { type: 'set_spoken_language', label: 'Set spoken language to Auto-detect', payload: { spoken_language: 'auto' } },
    { type: 'set_sidebar_label_auto', label: 'Sidebar label: Auto' },
    { type: 'set_sidebar_label_username', label: 'Sidebar label: Username' },
    { type: 'set_sidebar_label_email', label: 'Sidebar label: Email' },
  ];
  const MEETING_CHOICE_FALLBACK_ACTIONS: ActionCard[] = [
    { type: 'start_meeting', label: 'Start a live meeting' },
    { type: 'upload_meeting', label: 'Upload a meeting recording' },
  ];
  const appLanguageOptions = [
    { value: 'en', label: 'English' },
    { value: 'es', label: 'Spanish' },
    { value: 'fr', label: 'French' },
    { value: 'de', label: 'German' },
    { value: 'it', label: 'Italian' },
    { value: 'pt', label: 'Portuguese' },
    { value: 'nl', label: 'Dutch' },
    { value: 'sv', label: 'Swedish' },
    { value: 'da', label: 'Danish' },
    { value: 'no', label: 'Norwegian' },
    { value: 'fi', label: 'Finnish' },
    { value: 'pl', label: 'Polish' },
    { value: 'cs', label: 'Czech' },
    { value: 'ro', label: 'Romanian' },
    { value: 'hu', label: 'Hungarian' },
    { value: 'tr', label: 'Turkish' },
    { value: 'ru', label: 'Russian' },
    { value: 'uk', label: 'Ukrainian' },
    { value: 'el', label: 'Greek' },
    { value: 'he', label: 'Hebrew' },
    { value: 'ar', label: 'Arabic' },
    { value: 'hi', label: 'Hindi' },
    { value: 'bn', label: 'Bengali' },
    { value: 'ta', label: 'Tamil' },
    { value: 'te', label: 'Telugu' },
    { value: 'ja', label: 'Japanese' },
    { value: 'ko', label: 'Korean' },
    { value: 'zh', label: 'Chinese' },
    { value: 'id', label: 'Indonesian' },
    { value: 'vi', label: 'Vietnamese' },
    { value: 'th', label: 'Thai' },
    { value: 'ms', label: 'Malay' },
  ];
  let mode: AppMode = 'none';
  const showMode = writable(mode);

  let liveTranscriberComponent: LiveTranscriber;
  let isRecording = false;
  let isPaused = false;
  let enableSpeakers = true;
  let enrollmentFinalized = false;
  let meetingAttendees: string[] = [];
  let isHistoricalMeeting = false;
  let showUserMenu = false;
  let chatInput = '';
  let chatItems: { id: string; title: string }[] = [];
  let meetingItems: { id: string; title: string; source?: string; meeting_date?: string }[] = [];
  let activeMeetingId = '';
  let activeMeetingPayload: any = null;
  let activeChatId = '';
  let chatMessages: ChatMessage[] = [];
  let chatLoading = false;
  let isSendingMessage = false;
  let chatError = '';
  let pendingActions: ActionCard[] = [];
  let hiddenActions: ActionCard[] = [];
  let sidebarLabelActions: ActionCard[] = [];
  let themeActions: ActionCard[] = [];
  let languageActions: ActionCard[] = [];
  let regularPendingActions: ActionCard[] = [];
  let selectedSidebarLabelActionType = '';
  let selectedThemeActionType = '';
  let selectedLanguageActionValue = 'app:en';
  let chatDocked = false;
  let chatScrollEl: HTMLDivElement | null = null;
  let chatInputEl: HTMLTextAreaElement | null = null;
  let lastRenderedMessageCount = 0;
  let authToken = '';
  let authMode: 'login' | 'register' = 'login';
  let authEmail = '';
  let authPassword = '';
  let authUsername = '';
  let authDisplayName = '';
  let authLoading = false;
  let authError = '';
  let currentUser: AppUser | null = null;
  let chatMinimized = true;
  let authenticated = false;
  let accountUsername = '';
  let accountDisplayName = '';
  let accountSaving = false;
  let accountNotice = '';
  let accountError = '';
  let settingsSaving = false;
  let settingsNotice = '';
  let settingsError = '';
  let settingsLoading = false;
  let showSettingsModal = false;
  let showAccountModal = false;
  let isVoiceRecording = false;
  let voiceTranscript = '';
  let voiceError = '';
  let voiceAudioContext: AudioContext | null = null;
  let voiceMediaStream: MediaStream | null = null;
  let voiceProcessor: ScriptProcessorNode | null = null;
  let voiceTranscribeSocket: WebSocket | null = null;
  let voiceBuffer: Float32Array[] = [];
  let voiceStartTime = 0;
  let voiceLastSoundTime = 0;
  let voiceSilenceCheckInterval: any = null;
  let voiceHasSpeech = false;
  let voiceSessionId = 0;
  let voiceAutoListenEnabled = false;
  let voiceContextKey = '';
  const VOICE_WS_URL = getWSURL('ws-transcribe');
  const VOICE_SILENCE_MS = 900;
  const VOICE_SILENCE_THRESHOLD = 0.015;
  const VOICE_MIN_SAMPLE_MS = 1500;
  const VOICE_MAX_SAMPLE_MS = 15000;
  const API_BASE = getAPIBaseURL();
  const TOKEN_KEY = 'meetsum_token';

  $: isHistoricalMeeting = mode === 'upload' && Boolean(activeMeetingPayload?.meeting?.id);
  const USER_KEY = 'meetsum_user';
  const APP_VERSION = '0.0.0';

  const whisperLanguageOptions = [
    { value: 'auto', label: 'Auto-detect' },
    { value: 'af', label: 'Afrikaans' },
    { value: 'am', label: 'Amharic' },
    { value: 'ar', label: 'Arabic' },
    { value: 'hy', label: 'Armenian' },
    { value: 'as', label: 'Assamese' },
    { value: 'az', label: 'Azerbaijani' },
    { value: 'eu', label: 'Basque' },
    { value: 'be', label: 'Belarusian' },
    { value: 'bn', label: 'Bengali' },
    { value: 'bs', label: 'Bosnian' },
    { value: 'bg', label: 'Bulgarian' },
    { value: 'my', label: 'Burmese' },
    { value: 'ca', label: 'Catalan' },
    { value: 'zh', label: 'Chinese' },
    { value: 'hr', label: 'Croatian' },
    { value: 'cs', label: 'Czech' },
    { value: 'da', label: 'Danish' },
    { value: 'nl', label: 'Dutch' },
    { value: 'en', label: 'English' },
    { value: 'et', label: 'Estonian' },
    { value: 'fi', label: 'Finnish' },
    { value: 'fr', label: 'French' },
    { value: 'gl', label: 'Galician' },
    { value: 'ka', label: 'Georgian' },
    { value: 'de', label: 'German' },
    { value: 'el', label: 'Greek' },
    { value: 'gu', label: 'Gujarati' },
    { value: 'he', label: 'Hebrew' },
    { value: 'hi', label: 'Hindi' },
    { value: 'hu', label: 'Hungarian' },
    { value: 'is', label: 'Icelandic' },
    { value: 'id', label: 'Indonesian' },
    { value: 'it', label: 'Italian' },
    { value: 'ja', label: 'Japanese' },
    { value: 'jw', label: 'Javanese' },
    { value: 'kn', label: 'Kannada' },
    { value: 'kk', label: 'Kazakh' },
    { value: 'km', label: 'Khmer' },
    { value: 'ko', label: 'Korean' },
    { value: 'lo', label: 'Lao' },
    { value: 'la', label: 'Latin' },
    { value: 'lv', label: 'Latvian' },
    { value: 'lt', label: 'Lithuanian' },
    { value: 'mk', label: 'Macedonian' },
    { value: 'ms', label: 'Malay' },
    { value: 'ml', label: 'Malayalam' },
    { value: 'mt', label: 'Maltese' },
    { value: 'mi', label: 'Maori' },
    { value: 'mr', label: 'Marathi' },
    { value: 'mn', label: 'Mongolian' },
    { value: 'ne', label: 'Nepali' },
    { value: 'no', label: 'Norwegian' },
    { value: 'fa', label: 'Persian' },
    { value: 'pl', label: 'Polish' },
    { value: 'pt', label: 'Portuguese' },
    { value: 'pa', label: 'Punjabi' },
    { value: 'ro', label: 'Romanian' },
    { value: 'ru', label: 'Russian' },
    { value: 'sr', label: 'Serbian' },
    { value: 'si', label: 'Sinhala' },
    { value: 'sk', label: 'Slovak' },
    { value: 'sl', label: 'Slovenian' },
    { value: 'es', label: 'Spanish' },
    { value: 'sw', label: 'Swahili' },
    { value: 'sv', label: 'Swedish' },
    { value: 'tl', label: 'Tagalog' },
    { value: 'ta', label: 'Tamil' },
    { value: 'te', label: 'Telugu' },
    { value: 'th', label: 'Thai' },
    { value: 'tr', label: 'Turkish' },
    { value: 'uk', label: 'Ukrainian' },
    { value: 'ur', label: 'Urdu' },
    { value: 'uz', label: 'Uzbek' },
    { value: 'vi', label: 'Vietnamese' },
    { value: 'cy', label: 'Welsh' },
    { value: 'yi', label: 'Yiddish' },
    { value: 'yo', label: 'Yoruba' },
  ];

  const createDefaultSettings = (): AppSettings => ({
    theme: 'dark',
    language: 'en',
    spokenLanguage: 'auto',
    accountLabelMode: 'auto',
  });

  let appSettings: AppSettings = createDefaultSettings();

  $: authenticated = Boolean(authToken);
  $: chatDocked = mode === 'chat' && (chatLoading || chatMessages.length > 0);
  $: applyTheme(appSettings.theme);
  $: sidebarLabelActions = pendingActions.filter((action) => SIDEBAR_LABEL_ACTION_TYPES.includes(action.type));
  $: themeActions = pendingActions.filter((action) => THEME_ACTION_TYPES.includes(action.type));
  $: languageActions = pendingActions.filter((action) => LANGUAGE_ACTION_TYPES.includes(action.type));
  $: regularPendingActions = pendingActions.filter(
    (action) => !SIDEBAR_LABEL_ACTION_TYPES.includes(action.type)
      && !THEME_ACTION_TYPES.includes(action.type)
      && !LANGUAGE_ACTION_TYPES.includes(action.type)
  );
  $: {
    const hasSelected = sidebarLabelActions.some((action) => action.type === selectedSidebarLabelActionType);
    if (!sidebarLabelActions.length) {
      selectedSidebarLabelActionType = '';
    } else if (!hasSelected) {
      selectedSidebarLabelActionType = sidebarLabelActions[0].type;
    }
  }
  $: {
    const hasSelected = themeActions.some((action) => action.type === selectedThemeActionType);
    if (!themeActions.length) {
      selectedThemeActionType = '';
    } else if (!hasSelected) {
      selectedThemeActionType = themeActions[0].type;
    }
  }
  $: {
    if (!languageActions.length) {
      selectedLanguageActionValue = 'app:en';
    }
  }

  const isAuthenticated = () => authenticated;

  function getDisplayName() {
    if (!currentUser) return 'User';
    if (appSettings.accountLabelMode === 'display_name' && currentUser.display_name) return currentUser.display_name;
    if (appSettings.accountLabelMode === 'username' && currentUser.username) return currentUser.username;
    if (appSettings.accountLabelMode === 'email' && currentUser.email) return currentUser.email;
    return currentUser.display_name || currentUser.username || currentUser.email || 'User';
  }

  function applyTheme(theme: AppSettings['theme']) {
    if (typeof document === 'undefined') return;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  }

  function mapSettingsFromApi(raw: any): AppSettings {
    return {
      theme: raw?.theme === 'light' ? 'light' : 'dark',
      language: 'en',
      spokenLanguage: raw?.spoken_language || raw?.spokenLanguage || 'auto',
      accountLabelMode: ['display_name', 'username', 'email'].includes(raw?.account_label_mode)
        ? raw.account_label_mode
        : raw?.accountLabelMode === 'display_name' || raw?.accountLabelMode === 'username' || raw?.accountLabelMode === 'email'
          ? raw.accountLabelMode
          : 'auto',
    };
  }

  function mapSettingsToApi(settings: AppSettings) {
    return {
      theme: settings.theme,
      language: settings.language,
      spoken_language: settings.spokenLanguage,
      account_label_mode: settings.accountLabelMode,
    };
  }

  function getInitials() {
    const name = getDisplayName().trim();
    if (!name) return 'US';
    const parts = name.split(/\s+/).filter(Boolean);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0] || ''}${parts[1][0] || ''}`.toUpperCase();
  }

  function normalizeChatMessages(items: ChatMessage[]) {
    return [...items].sort((a, b) => {
      if (!a.created_at || !b.created_at) return 0;
      const aTime = new Date(a.created_at).getTime();
      const bTime = new Date(b.created_at).getTime();
      if (Number.isNaN(aTime) || Number.isNaN(bTime)) return 0;
      return aTime - bTime;
    });
  }

  function persistAuth(token: string, user: any) {
    authToken = token;
    currentUser = user;
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    syncAccountForm();
  }

  function clearAuth() {
    authToken = '';
    currentUser = null;
    appSettings = createDefaultSettings();
    chatItems = [];
    meetingItems = [];
    activeMeetingId = '';
    activeChatId = '';
    accountUsername = '';
    accountDisplayName = '';
    pendingActions = [];
    hiddenActions = [];
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  async function loadAppSettings() {
    if (!authToken) {
      appSettings = createDefaultSettings();
      return;
    }

    settingsLoading = true;
    settingsError = '';
    try {
      const payload = await apiFetch('/auth/settings');
      appSettings = mapSettingsFromApi(payload.settings || {});
    } catch (error: any) {
      settingsError = error?.message || 'Unable to load settings.';
      appSettings = createDefaultSettings();
    } finally {
      settingsLoading = false;
    }
  }

  function syncAccountForm() {
    accountUsername = currentUser?.username || '';
    accountDisplayName = currentUser?.display_name || '';
  }

  async function refreshCurrentUser() {
    if (!authToken) return;
    const payload = await apiFetch('/auth/me');
    currentUser = payload.user;
    localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
    syncAccountForm();
  }

  async function apiFetch(path: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers || {});
    if (!headers.has('Content-Type') && options.body) {
      headers.set('Content-Type', 'application/json');
    }
    if (authToken) {
      headers.set('Authorization', `Bearer ${authToken}`);
    }

    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    if (res.status === 401) {
      clearAuth();
      throw new Error('Session expired. Please sign in again.');
    }

    if (!res.ok) {
      const rawBody = await res.text();
      let message = rawBody;
      try {
        const payload = JSON.parse(rawBody || '{}');
        message = payload?.detail || payload?.message || rawBody;
      } catch {
        message = rawBody;
      }
      throw new Error(message || `Request failed (${res.status})`);
    }

    return res.json();
  }

  async function fetchSidebarData() {
    if (!authToken) return;
    const [chats, meetings] = await Promise.all([
      apiFetch('/sidebar/chats'),
      apiFetch('/sidebar/meetings'),
    ]);
    chatItems = chats.items || [];
    meetingItems = meetings.items || [];
    if (!activeMeetingId && meetingItems.length) {
      activeMeetingId = meetingItems[0].id;
    }
    if (!activeChatId && chatItems.length) activeChatId = chatItems[0].id;
  }

  async function fetchChatMessages(chatId: string) {
    if (!isAuthenticated() || !chatId) return;
    chatLoading = true;
    try {
      const payload = await apiFetch(`/sidebar/chats/${chatId}/messages`);
      chatMessages = normalizeChatMessages(payload.items || []);
      chatError = '';
    } catch (error: any) {
      chatError = error?.message || 'Unable to load chat messages.';
      chatMessages = [];
    } finally {
      chatLoading = false;
      await scrollChatToBottom();
    }
  }

  async function openChat(chatId: string) {
    if (!isAuthenticated() || !chatId) return;
    await stopVoiceCapture();
    activeChatId = chatId;
    activeMeetingPayload = null;
    mode = 'chat';
    showMode.set(mode);
    chatMinimized = false;
    pendingActions = [];
    hiddenActions = [];
    await fetchChatMessages(chatId);
  }

  async function scrollChatToBottom() {
    await tick();
    if (chatScrollEl) {
      chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
    }
  }

  async function submitAuth() {
    authLoading = true;
    authError = '';
    try {
      const payload: Record<string, string> = {
        email: authEmail.trim(),
        password: authPassword,
      };
      if (authMode === 'register') {
        payload.username = authUsername.trim();
        payload.display_name = authDisplayName.trim();
      }

      const data = await apiFetch(`/auth/${authMode}`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      persistAuth(data.access_token, data.user);
      authPassword = '';
      await refreshCurrentUser();
      await fetchSidebarData();
    } catch (error: any) {
      authError = error?.message || 'Authentication failed';
      if (String(authError).toLowerCase().includes('failed to fetch')) {
        authError = 'Cannot connect to backend. Ensure your API server is running and accessible.';
      }
    } finally {
      authLoading = false;
    }
  }

  async function createNewChat() {
    if (!isAuthenticated()) return;
    await stopVoiceCapture();
    const created = await apiFetch('/sidebar/chats', {
      method: 'POST',
      body: JSON.stringify({ title: 'New chat' }),
    });
    activeChatId = created.id;
    mode = 'chat';
    showMode.set(mode);
    chatMinimized = false;
    chatMessages = [];
    chatError = '';
    isSendingMessage = false;
    pendingActions = [];
    hiddenActions = [];
    await fetchSidebarData();
  }

  async function openChatInterfaceFromIntro() {
    await stopVoiceCapture();
    mode = 'chat';
    showMode.set(mode);
    activeChatId = '';
    activeMeetingPayload = null;
    chatMessages = [];
    chatLoading = false;
    chatError = '';
    isSendingMessage = false;
    chatMinimized = false;
  }

  function toggleUserMenu() {
    showUserMenu = !showUserMenu;
  }

  function closeUserMenu() {
    showUserMenu = false;
  }

  function closeSettingsModal() {
    showSettingsModal = false;
  }

  function closeAccountModal() {
    showAccountModal = false;
  }

  async function openUserView(view: 'settings' | 'admin' | 'account') {
    closeUserMenu();
    await stopVoiceCapture();
    if (view === 'settings') {
      settingsNotice = '';
      settingsError = '';
      await loadAppSettings();
      showSettingsModal = true;
      return;
    }
    if (view === 'account') {
      accountNotice = '';
      accountError = '';
      syncAccountForm();
      await loadAppSettings();
      showAccountModal = true;
      return;
    }
    mode = view;
    showMode.set(mode);
    chatMinimized = true;
    activeMeetingPayload = null;
  }

  async function saveAccountChanges() {
    if (!isAuthenticated()) return;
    accountSaving = true;
    accountNotice = '';
    accountError = '';
    try {
      const profilePayload = await apiFetch('/auth/me', {
        method: 'PATCH',
        body: JSON.stringify({
          username: accountUsername,
          display_name: accountDisplayName,
        }),
      });
      const settingsPayload = await apiFetch('/auth/settings', {
        method: 'PATCH',
        body: JSON.stringify(mapSettingsToApi(appSettings)),
      });
      currentUser = profilePayload.user;
      appSettings = mapSettingsFromApi(settingsPayload.settings || {});
      localStorage.setItem(USER_KEY, JSON.stringify(profilePayload.user));
      syncAccountForm();
      accountNotice = 'Account updated.';
    } catch (error: any) {
      accountError = error?.message || 'Unable to update account.';
    } finally {
      accountSaving = false;
    }
  }

  async function saveAppSettings() {
    if (!isAuthenticated()) return;
    settingsSaving = true;
    settingsNotice = '';
    settingsError = '';
    try {
      const payload = await apiFetch('/auth/settings', {
        method: 'PATCH',
        body: JSON.stringify(mapSettingsToApi(appSettings)),
      });
      appSettings = mapSettingsFromApi(payload.settings || {});
      settingsNotice = 'Settings saved to your account.';
    } catch (error: any) {
      settingsError = error?.message || 'Unable to save settings.';
    } finally {
      settingsSaving = false;
    }
  }

  function closeAllItemMenus(exceptEl?: HTMLDetailsElement | null) {
    const menus = document.querySelectorAll<HTMLDetailsElement>('details.item-menu-wrap[open]');
    menus.forEach((menu) => {
      if (exceptEl && menu === exceptEl) return;
      menu.open = false;
    });
  }

  function handleItemMenuToggle(event: Event) {
    const details = event.currentTarget as HTMLDetailsElement;
    if (!details?.open) return;
    closeAllItemMenus(details);
  }

  async function selectRecord() {
    await stopVoiceCapture();
    const wasHistoricalMeeting = isHistoricalMeeting || Boolean(activeMeetingPayload?.meeting?.id);
    mode = 'record';
    enrollmentFinalized = false;
    if (wasHistoricalMeeting) {
      meetingAttendees = [];
    }
    chatMessages = [];
    showMode.set(mode);
    chatMinimized = true;

    // Wait for the LiveTranscriber component to mount
    await tick();
    if (liveTranscriberComponent) {
      liveTranscriberComponent.toggleMeeting(); // auto-start recording
    }
  }

  async function openMeetingOptions() {
    await stopVoiceCapture();
    const wasHistoricalMeeting = isHistoricalMeeting || Boolean(activeMeetingPayload?.meeting?.id);
    mode = 'meeting';
    enrollmentFinalized = false;
    if (wasHistoricalMeeting) {
      meetingAttendees = [];
    }
    chatMessages = [];
    activeMeetingPayload = null;
    showMode.set(mode);
    chatMinimized = true;
  }

  async function selectUpload() {
    await stopVoiceCapture();
    const wasHistoricalMeeting = isHistoricalMeeting || Boolean(activeMeetingPayload?.meeting?.id);
    mode = 'upload';
    enrollmentFinalized = false;
    if (wasHistoricalMeeting) {
      meetingAttendees = [];
    }
    chatMessages = [];
    activeMeetingPayload = null;
    showMode.set(mode);
    chatMinimized = true;
  }

  function goToFrontPage() {
    void stopVoiceCapture();
    mode = 'none';
    showMode.set(mode);
    activeMeetingPayload = null;
    activeMeetingId = '';
    activeChatId = '';
    chatMessages = [];
    chatLoading = false;
    chatError = '';
    isSendingMessage = false;
    chatMinimized = true;
  }

  async function openMeeting(meetingId: string) {
    if (!isAuthenticated()) return;
    await stopVoiceCapture();
    try {
      const payload = await apiFetch(`/sidebar/meetings/${meetingId}`);
      activeMeetingId = meetingId;
      activeMeetingPayload = payload;
      enableSpeakers = false;
      enrollmentFinalized = true;
      meetingAttendees = Array.isArray(payload?.meeting_attendees)
        ? payload.meeting_attendees.map((name: any) => String(name || '').trim()).filter(Boolean)
        : [];
      mode = 'upload';
      chatMessages = [];
      showMode.set(mode);
      chatMinimized = true;
    } catch (error) {
      console.error(error);
    }
  }

  function handleAttendeesFinalized(event: CustomEvent<{ attendees: string[] }>) {
    meetingAttendees = Array.isArray(event?.detail?.attendees) ? event.detail.attendees : [];
  }

  function handleAttendeesChanged(event: CustomEvent<{ attendees: string[] }>) {
    if (isHistoricalMeeting) return;
    meetingAttendees = Array.isArray(event?.detail?.attendees) ? event.detail.attendees : [];
  }

  async function renameMeeting(meeting: { id: string; title: string }) {
    if (!isAuthenticated()) return;
    const nextTitle = window.prompt('Rename meeting', meeting.title);
    if (nextTitle === null) return;
    const title = nextTitle.trim();
    if (!title || title === meeting.title) return;
    try {
      await apiFetch(`/sidebar/meetings/${meeting.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      });
      await fetchSidebarData();
    } catch (error) {
      console.error(error);
    }
  }

  async function deleteMeeting(meetingId: string) {
    if (!isAuthenticated()) return;
    if (!window.confirm('Delete this meeting?')) return;
    try {
      await apiFetch(`/sidebar/meetings/${meetingId}`, {
        method: 'DELETE',
      });
      if (activeMeetingId === meetingId) {
        activeMeetingId = '';
        activeMeetingPayload = null;
      }
      await fetchSidebarData();
    } catch (error) {
      console.error(error);
    }
  }

  async function renameChat(chat: { id: string; title: string }) {
    if (!isAuthenticated()) return;
    const nextTitle = window.prompt('Rename chat', chat.title);
    if (nextTitle === null) return;
    const title = nextTitle.trim();
    if (!title || title === chat.title) return;
    try {
      await apiFetch(`/sidebar/chats/${chat.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      });
      await fetchSidebarData();
    } catch (error) {
      console.error(error);
    }
  }

  async function deleteChat(chatId: string) {
    if (!isAuthenticated()) return;
    if (!window.confirm('Delete this chat?')) return;
    try {
      await apiFetch(`/sidebar/chats/${chatId}`, {
        method: 'DELETE',
      });
      if (activeChatId === chatId) {
        activeChatId = '';
        chatMessages = [];
        if (mode === 'chat') {
          mode = 'none';
          showMode.set(mode);
        }
      }
      await fetchSidebarData();
      if (!activeChatId && chatItems.length) {
        await openChat(chatItems[0].id);
      }
    } catch (error) {
      console.error(error);
    }
  }

  function toggleChatMinimized() {
    chatMinimized = !chatMinimized;
  }

  async function stopVoiceCapture() {
    // Invalidate any in-flight start request so capture cannot start after a forced stop.
    voiceSessionId += 1;
    voiceAutoListenEnabled = false;
    voiceContextKey = '';
    if (voiceSilenceCheckInterval) {
      clearInterval(voiceSilenceCheckInterval);
      voiceSilenceCheckInterval = null;
    }
    isVoiceRecording = false;

    if (voiceProcessor) {
      voiceProcessor.disconnect();
      voiceProcessor = null;
    }
    if (voiceMediaStream) {
      voiceMediaStream.getTracks().forEach((track) => track.stop());
      voiceMediaStream = null;
    }
    if (voiceAudioContext) {
      await voiceAudioContext.close();
      voiceAudioContext = null;
    }
    if (voiceTranscribeSocket) {
      try {
        if (voiceTranscribeSocket.readyState === WebSocket.OPEN || voiceTranscribeSocket.readyState === WebSocket.CONNECTING) {
          voiceTranscribeSocket.close();
        }
      } catch {
        // Ignore close race during teardown.
      }
      voiceTranscribeSocket = null;
    }

    voiceBuffer = [];
    voiceHasSpeech = false;
    voiceTranscript = '';
    voiceError = '';
  }

  function getVoiceAwarePlaceholder(defaultPlaceholder: string) {
    return defaultPlaceholder;
  }

  function getVoiceInlineStatus() {
    if (voiceTranscript) return voiceTranscript;
    if (isVoiceRecording) return 'Listening...';
    if (voiceError) return voiceError;
    return '';
  }

  function getVoiceContextKey() {
    return `${mode}|chat:${activeChatId || 'none'}|meeting:${activeMeetingId || 'none'}`;
  }

  function canAutoContinueVoice() {
    const modeSupportsChatInput = mode === 'chat' || mode === 'record' || mode === 'upload';
    return voiceAutoListenEnabled && modeSupportsChatInput;
  }

  async function handleVoiceMicToggle() {
    if (isVoiceRecording || voiceAutoListenEnabled) {
      await stopVoiceCapture();
      return;
    }

    voiceAutoListenEnabled = true;
    voiceContextKey = getVoiceContextKey();
    await startVoiceInput(true);
  }

  async function executeAction(action: ActionCard) {
    if (!action) return;
    if (action.type === 'start_meeting') {
      await openMeetingOptions();
    } else if (action.type === 'upload_meeting') {
      await selectUpload();
    } else if (action.type === 'start_speaker_enrollment') {
      await openMeetingOptions();
      enableSpeakers = true;
      enrollmentFinalized = false;
    } else if (action.type === 'new_chat') {
      void createNewChat();
    } else if (action.type === 'rename_meeting') {
      if (activeMeetingPayload?.meeting) {
        void renameMeeting(activeMeetingPayload.meeting);
      }
    } else if (action.type === 'open_settings') {
      await openUserView('settings');
    } else if (action.type === 'set_theme_light') {
      appSettings = { ...appSettings, theme: 'light' };
      await saveAppSettings();
    } else if (action.type === 'set_theme_dark') {
      appSettings = { ...appSettings, theme: 'dark' };
      await saveAppSettings();
    } else if (action.type === 'set_language_en') {
      appSettings = { ...appSettings, language: 'en' };
      await saveAppSettings();
    } else if (action.type === 'set_spoken_language') {
      const spoken = String(action.payload?.spoken_language || '').trim();
      if (!spoken) return;
      appSettings = { ...appSettings, spokenLanguage: spoken };
      await saveAppSettings();
    } else if (action.type === 'set_sidebar_label_auto') {
      appSettings = { ...appSettings, accountLabelMode: 'auto' };
      await saveAppSettings();
    } else if (action.type === 'set_sidebar_label_display_name') {
      appSettings = { ...appSettings, accountLabelMode: 'display_name' };
      await saveAppSettings();
    } else if (action.type === 'set_sidebar_label_username') {
      appSettings = { ...appSettings, accountLabelMode: 'username' };
      await saveAppSettings();
    } else if (action.type === 'set_sidebar_label_email') {
      appSettings = { ...appSettings, accountLabelMode: 'email' };
      await saveAppSettings();
    } else if (action.type === 'chat_general_mode') {
      mode = 'chat';
      showMode.set(mode);
      pendingActions = [];
      hiddenActions = [];
      chatMessages = [
        ...chatMessages,
        {
          id: `local-assistant-mode-${Date.now()}`,
          role: 'assistant',
          content: 'Sure. What would you like to discuss?',
        },
      ];
      await scrollChatToBottom();
    }
  }

  function dismissAction() {
    hiddenActions = [...pendingActions];
    pendingActions = [];
  }

  function showHiddenActions() {
    if (!hiddenActions.length) return;
    pendingActions = [...hiddenActions];
    hiddenActions = [];
  }

  function executeActionByType(actionType: string) {
    const action = pendingActions.find((item) => item.type === actionType);
    if (!action) return;
    void executeAction(action);
  }

  async function executeLanguageActionSelection() {
    const [scope, value] = selectedLanguageActionValue.split(':', 2);
    if (!scope || !value) return;
    if (scope === 'app') {
      appSettings = { ...appSettings, language: value };
      await saveAppSettings();
      return;
    }
    if (scope === 'spoken') {
      appSettings = { ...appSettings, spokenLanguage: value };
      await saveAppSettings();
    }
  }

  function submitSuggestedMessage(message: string) {
    chatInput = message;
    submitChatPlaceholder();
  }

  function isCapabilityPrompt(text: string) {
    const normalized = text.trim().toLowerCase();
    if (!normalized) return false;
    return /\b(agentic\s+(options|capabilities)|what\s+can\s+you\s+do|how\s+can\s+you\s+help|show\s+me\s+what\s+you\s+can\s+do)\b/.test(
      normalized,
    );
  }

  function isGenericMeetingPrompt(text: string) {
    const normalized = text.trim().toLowerCase();
    if (!normalized) return false;
    if (!/\bmeeting\b/.test(normalized)) return false;
    if (/\b(upload|uploaded|import|file|audio|record|recording|transcribe|rename|title|name)\b/.test(normalized)) return false;
    return /\b(open|start|begin|launch|create|new|help)\b/.test(normalized);
  }

  function inferMeetingActionFromText(text: string): 'start_meeting' | 'upload_meeting' | null {
    const normalized = text.trim().toLowerCase().replace(/[-_/]+/g, ' ');
    if (!normalized) return null;

    const uploadMeeting = /(upload|uploaded|import|transcribe).{0,30}(meeting|audio|record|recording|file)/.test(normalized)
      || /(meeting|audio|record|recording|file).{0,30}(upload|uploaded|import|transcribe)/.test(normalized)
      || /\b(upload|uploaded|import)\b.*\b(record|recording|audio|file)\b/.test(normalized);
    if (uploadMeeting) return 'upload_meeting';

    const liveMeeting = /(start|begin|open|activate|enable).{0,30}live\s+meeting|\blive\s+meeting\b|\bstart\s+a\s+live\b/.test(normalized)
      || /\blive\b.{0,20}\bmeeting\b/.test(normalized);
    if (liveMeeting) return 'start_meeting';

    return null;
  }

  function selectPreferredAction(messageText: string, actions: ActionCard[]): ActionCard | null {
    const normalized = messageText.trim().toLowerCase().replace(/[-_/]+/g, ' ');
    if (!normalized || !actions.length) return null;

    const byType = new Map(actions.map((action) => [action.type, action]));
    const hasMeetingPair = byType.has('start_meeting') && byType.has('upload_meeting');

    // Keep both options for generic meeting asks (ambiguous: no live/upload hint).
    if (hasMeetingPair && /(start|begin|open|activate|enable).{0,30}meeting/.test(normalized)) {
      const mentionsSpecificPath = /\b(live|upload|recording|audio|file)\b/.test(normalized);
      if (!mentionsSpecificPath) return null;
    }

    if (/(start|begin|open|activate|enable).{0,30}live\s+meeting|\blive\s+meeting\b|\bstart\s+a\s+live\b/.test(normalized)) {
      return byType.get('start_meeting') || null;
    }

    if (/(upload|uploaded|import|transcribe).{0,30}(meeting|audio|record|recording|file)/.test(normalized)
      || /(meeting|audio|record|recording|file).{0,30}(upload|uploaded|import|transcribe)/.test(normalized)) {
      return byType.get('upload_meeting') || null;
    }

    if (/(dark\s+mode|theme.{0,20}dark|activate.{0,20}dark|turn on.{0,20}dark)/.test(normalized)) {
      return byType.get('set_theme_dark') || null;
    }

    if (/(light\s+mode|theme.{0,20}light|activate.{0,20}light|turn on.{0,20}light)/.test(normalized)) {
      return byType.get('set_theme_light') || null;
    }

    return null;
  }

  function buildVoiceActionAcknowledgement(action: ActionCard): string {
    switch (action.type) {
      case 'start_meeting':
        return 'Acknowledged. Opening meeting setup now.';
      case 'upload_meeting':
        return 'Acknowledged. Opening upload meeting now.';
      case 'set_theme_dark':
        return 'Acknowledged. Switching to dark mode now.';
      case 'set_theme_light':
        return 'Acknowledged. Switching to light mode now.';
      case 'open_settings':
        return 'Acknowledged. Opening settings now.';
      case 'start_speaker_enrollment':
        return 'Acknowledged. Opening speaker enrollment now.';
      default:
        return `Acknowledged. ${action.label}.`;
    }
  }

  function startAgentIntro() {
    submitSuggestedMessage('Show me your agentic options in MeetSum.');
  }

  function submitChatPlaceholder() {
    const text = chatInput.trim();
    if (!text) return;
    if (!isAuthenticated()) {
      const title = text.length > 36 ? `${text.slice(0, 36)}...` : text;
      chatItems = [{ id: crypto.randomUUID(), title }, ...chatItems].slice(0, 8);
      chatInput = '';
      return;
    }

    void sendChatMessage(text);
  }

  async function sendChatMessage(content: string, fromVoice = false) {
    const messageText = content.trim();
    if (!messageText || isSendingMessage) return;

    const optimisticUserMessage: ChatMessage = {
      id: `local-user-${Date.now()}`,
      role: 'user',
      content: messageText,
    };
    const pendingAssistantId = `local-assistant-${Date.now()}`;
    const pendingAssistantMessage: ChatMessage = {
      id: pendingAssistantId,
      role: 'assistant',
      content: '',
      pending: true,
    };

    mode = 'chat';
    showMode.set(mode);
    activeMeetingPayload = null;
    pendingActions = [];
    hiddenActions = [];
    chatMinimized = false;
    chatError = '';
    isSendingMessage = true;
    chatInput = '';
    chatMessages = [...chatMessages, optimisticUserMessage, pendingAssistantMessage];
    await scrollChatToBottom();

    try {
      let chatId = activeChatId;
      if (!chatId) {
        const created = await apiFetch('/sidebar/chats', {
          method: 'POST',
          body: JSON.stringify({ title: 'New chat' }),
        });
        chatId = created.id;
        activeChatId = chatId;
        await fetchSidebarData();
      }

      const turn = await apiFetch(`/sidebar/chats/${chatId}/turn`, {
        method: 'POST',
        body: JSON.stringify({ message: messageText }),
      });

      chatMessages = chatMessages.filter((message) => message.id !== optimisticUserMessage.id && message.id !== pendingAssistantId);
      if (turn.user_message) chatMessages = [...chatMessages, turn.user_message];
      if (turn.assistant_message) chatMessages = [...chatMessages, turn.assistant_message];
      const actionList = [
        ...(Array.isArray(turn.actions) ? turn.actions : []),
        ...(turn.action ? [turn.action] : []),
      ];
      const seenActionTypes = new Set<string>();
      pendingActions = actionList
        .filter((item: any) => item && typeof item.type === 'string' && typeof item.label === 'string')
        .filter((item: any) => {
          if (seenActionTypes.has(item.type)) return false;
          seenActionTypes.add(item.type);
          return true;
        })
        .map((item: any) => ({ type: item.type, label: item.label, payload: item.payload || undefined }));

      if (!pendingActions.length) {
        const assistantText = String(turn?.assistant_message?.content || '');
        const inferredMeetingAction = inferMeetingActionFromText(messageText) || inferMeetingActionFromText(assistantText);
        if (inferredMeetingAction === 'start_meeting') {
          pendingActions = [{ type: 'start_meeting', label: 'Start a live meeting' }];
        } else if (inferredMeetingAction === 'upload_meeting') {
          pendingActions = [{ type: 'upload_meeting', label: 'Upload a meeting recording' }];
        } else if (isCapabilityPrompt(messageText)) {
          pendingActions = [...CAPABILITY_FALLBACK_ACTIONS];
        } else if (isGenericMeetingPrompt(messageText)) {
          pendingActions = [...MEETING_CHOICE_FALLBACK_ACTIONS];
        }
      }

      hiddenActions = [];
      chatError = '';
      await scrollChatToBottom();

      // Auto-execute when intent is unambiguous: single action or explicit option selection.
      const autoAction = pendingActions.length === 1
        ? pendingActions[0]
        : selectPreferredAction(messageText, pendingActions);
      if (autoAction) {
        chatMessages = [
          ...chatMessages,
          {
            id: `local-assistant-ack-${Date.now()}`,
            role: 'assistant',
            content: buildVoiceActionAcknowledgement(autoAction),
          },
        ];
        await scrollChatToBottom();
        const isMeetingNavigationAction = ['start_meeting', 'upload_meeting', 'start_speaker_enrollment'].includes(autoAction.type);
        if (!isMeetingNavigationAction) {
          pendingActions = pendingActions.filter((action) => action.type !== autoAction.type);
        }
        await executeAction(autoAction);
      }

      await fetchSidebarData();
      if (activeChatId) {
        await fetchChatMessages(activeChatId);
      }
    } catch (error: any) {
      chatError = error?.message || 'Unable to send message.';
      chatMessages = chatMessages.map((message) => {
        if (message.id !== pendingAssistantId) return message;
        return {
          ...message,
          pending: false,
          error: true,
          content: chatError,
        };
      });
      await scrollChatToBottom();
    } finally {
      isSendingMessage = false;
    }
  }

  function logout() {
    clearAuth();
    chatMessages = [];
    showUserMenu = false;
    showSettingsModal = false;
    showAccountModal = false;
    mode = 'none';
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

  function encodeWAV(samples: Float32Array, sampleRate: number) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    const writeString = (offset: number, str: string) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, 'data');
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
      let s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }

    return new Blob([view], { type: 'audio/wav' });
  }

  async function sendVoiceChunkToTranscribe(wavBlob: Blob, sampleRate: number) {
    return new Promise<string>((resolve, reject) => {
      const socket = new WebSocket(`${VOICE_WS_URL}?speakers=0&offset=0&attendees=%5B%5D`);
      voiceTranscribeSocket = socket;
      socket.binaryType = 'arraybuffer';
      let recognized = '';
      let settled = false;

      const settle = (fn: () => void) => {
        if (settled) return;
        settled = true;
        if (voiceTranscribeSocket === socket) {
          voiceTranscribeSocket = null;
        }
        fn();
      };

      socket.onopen = async () => {
        const buf = await wavBlob.arrayBuffer();
        socket.send(buf);
      };

      socket.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (Array.isArray(data.segments)) {
            recognized = data.segments.map((seg: any) => seg.text).join(' ').trim();
          } else if (data.text) {
            recognized = data.text.trim();
          }
          socket.close();
          settle(() => resolve(recognized));
        } catch (err) {
          console.error('Transcription error:', err);
          socket.close();
          settle(() => reject(err));
        }
      };

      socket.onerror = (err) => {
        console.error('WebSocket error:', err);
        settle(() => reject(err));
      };

      setTimeout(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.close();
          settle(() => resolve(recognized));
          return;
        }
        if (socket.readyState !== WebSocket.CLOSED) {
          socket.close();
          settle(() => resolve(recognized));
        }
      }, 10000);
    });
  }

  async function startVoiceInput(fromMicClick = false, fromAutoRestart = false) {
    if (!fromMicClick && !fromAutoRestart) return;
    if (fromAutoRestart && !canAutoContinueVoice()) return;
    if (isVoiceRecording) return;

    const sessionId = ++voiceSessionId;
    voiceError = '';
    voiceTranscript = '';
    isVoiceRecording = true;
    voiceBuffer = [];
    voiceStartTime = performance.now();
    voiceLastSoundTime = performance.now();
    voiceHasSpeech = false;

    // Check for silence periodically
    voiceSilenceCheckInterval = setInterval(() => {
      const now = performance.now();
      if (
        voiceHasSpeech &&
        now - voiceStartTime > VOICE_MIN_SAMPLE_MS &&
        now - voiceLastSoundTime > VOICE_SILENCE_MS
      ) {
        clearInterval(voiceSilenceCheckInterval);
        void stopVoiceInput(true);
        return;
      }
      if (now - voiceStartTime > VOICE_MAX_SAMPLE_MS) {
        clearInterval(voiceSilenceCheckInterval);
        void stopVoiceInput(true);
      }
    }, 100);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (sessionId !== voiceSessionId) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      voiceMediaStream = stream;

      voiceAudioContext = new AudioContext();
      voiceProcessor = voiceAudioContext.createScriptProcessor(4096, 1, 1);

      const source = voiceAudioContext.createMediaStreamSource(stream);
      source.connect(voiceProcessor);
      voiceProcessor.connect(voiceAudioContext.destination);

      voiceProcessor.onaudioprocess = (e) => {
        const chunk = e.inputBuffer.getChannelData(0).slice();
        voiceBuffer.push(chunk);

        // Silence detection: calculate RMS
        const rms = Math.sqrt(chunk.reduce((acc, s) => acc + s * s, 0) / chunk.length);
        if (rms > VOICE_SILENCE_THRESHOLD) {
          voiceLastSoundTime = performance.now();
          if (!voiceHasSpeech) {
            voiceHasSpeech = true;
            voiceTranscript = '🎤 Recording...';
          }
        }
      };
    } catch (err: any) {
      if (sessionId !== voiceSessionId) return;
      isVoiceRecording = false;
      voiceError = err?.message || 'Cannot access microphone';
    }
  }

  async function stopVoiceInput(allowAutoRestart = true) {
    const processingSessionId = voiceSessionId;
    if (voiceSilenceCheckInterval) {
      clearInterval(voiceSilenceCheckInterval);
      voiceSilenceCheckInterval = null;
    }
    isVoiceRecording = false;

    if (voiceProcessor) {
      voiceProcessor.disconnect();
      voiceProcessor = null;
    }
    if (voiceMediaStream) {
      voiceMediaStream.getTracks().forEach((track) => track.stop());
      voiceMediaStream = null;
    }
    const sampleRate = voiceAudioContext?.sampleRate || 44100;
    if (voiceAudioContext) {
      await voiceAudioContext.close();
      voiceAudioContext = null;
    }

    if (voiceBuffer.length === 0) {
      voiceError = 'No audio captured. Please try again.';
      if (allowAutoRestart && canAutoContinueVoice()) {
        await new Promise(resolve => setTimeout(resolve, 300));
        await startVoiceInput(false, true);
      }
      return;
    }

    voiceTranscript = '🔄 Processing...';

    try {
      const flat = flattenBuffers(voiceBuffer);
      const wavBlob = encodeWAV(flat, sampleRate);
      voiceBuffer = [];

      const recognized = await sendVoiceChunkToTranscribe(wavBlob, sampleRate);
      if (processingSessionId !== voiceSessionId) {
        return;
      }

      if (recognized) {
        voiceTranscript = recognized;
        await new Promise(resolve => setTimeout(resolve, 200));
        await sendChatMessage(recognized, true);
        voiceTranscript = '';
        voiceError = '';
        if (allowAutoRestart && canAutoContinueVoice()) {
          await new Promise(resolve => setTimeout(resolve, 300));
          await startVoiceInput(false, true);
        }
      } else {
        voiceTranscript = '';
        voiceError = 'No speech recognized. Try again.';
        if (allowAutoRestart && canAutoContinueVoice()) {
          await new Promise(resolve => setTimeout(resolve, 300));
          await startVoiceInput(false, true);
        }
      }
    } catch (err: any) {
      if (processingSessionId !== voiceSessionId) {
        return;
      }
      voiceTranscript = '';
      voiceError = err?.message || 'Transcription failed';
      if (allowAutoRestart && canAutoContinueVoice()) {
        await new Promise(resolve => setTimeout(resolve, 300));
        await startVoiceInput(false, true);
      }
    }
  }

  onMount(async () => {
    const token = localStorage.getItem(TOKEN_KEY) || '';
    const userRaw = localStorage.getItem(USER_KEY);
    if (!token || !userRaw) return;

    try {
      authToken = token;
      currentUser = JSON.parse(userRaw);
      syncAccountForm();
      await refreshCurrentUser();
      await loadAppSettings();
      await fetchSidebarData();
    } catch {
      clearAuth();
    }

    const handleGlobalPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('details.item-menu-wrap')) return;
      closeAllItemMenus();
    };

    window.addEventListener('pointerdown', handleGlobalPointerDown, true);
    return () => {
      window.removeEventListener('pointerdown', handleGlobalPointerDown, true);
    };
  });

  $: if (!enableSpeakers && mode === 'record' && !isHistoricalMeeting) {
    enrollmentFinalized = false;
    meetingAttendees = [];
  }

  $: if (mode === 'chat' && chatMessages.length !== lastRenderedMessageCount) {
    lastRenderedMessageCount = chatMessages.length;
    void scrollChatToBottom();
  }

  $: if (voiceAutoListenEnabled && !canAutoContinueVoice()) {
    void stopVoiceCapture();
  }
</script>


<style>
  .app-shell {
    display: flex;
    width: 100%;
    height: 100vh;
    overflow: hidden;
    background: #242424;
  }

  .sidebar {
    width: 260px;
    background: #1a1a1a;
    border-right: 1px solid #2f2f2f;
    color: rgba(255, 255, 255, 0.87);
    padding: 14px 12px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    position: relative;
  }

  .logo-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px 14px;
    font-weight: 600;
    font-size: 0.95rem;
    border: none;
    background: transparent;
    color: rgba(255, 255, 255, 0.87);
    width: 100%;
    cursor: pointer;
    text-align: left;
    border-radius: 8px;
  }

  .logo-row:hover {
    background: #242424;
  }

  .logo-badge {
    width: 28px;
    height: 28px;
    border-radius: 8px;
    background: #3b3b3b;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 0.78rem;
    font-weight: 700;
  }

  .side-item,
  .side-pill,
  .user-button,
  .user-menu button {
    border-radius: 10px;
    border: 1px solid transparent;
    background: transparent;
    color: rgba(255, 255, 255, 0.87);
    text-align: left;
    width: 100%;
    padding: 9px 10px;
    font-size: 0.9rem;
    cursor: default;
  }

  .side-item {
    border-color: transparent;
    display: flex;
    align-items: center;
    gap: 8px;
    color: #e5e7eb;
    margin-bottom: 6px;
  }

  .side-item:hover {
    background: #242424;
  }

  .side-pill {
    border-color: transparent;
    display: flex;
    align-items: center;
    gap: 8px;
    color: #c7c7c7;
    margin-bottom: 6px;
  }

  .side-pill:hover {
    background: #242424;
  }

  .side-pill-icon {
    width: 16px;
    height: 16px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #a3a3a3;
    flex-shrink: 0;
  }

  .side-item-icon {
    width: 16px;
    height: 16px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #c7c7c7;
    flex-shrink: 0;
  }

  .section-label {
    margin: 12px 8px 6px;
    color: #a3a3a3;
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .meeting-group {
    margin-top: 6px;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 2px;
  }

  .meeting-row {
    display: flex;
    align-items: center;
    position: relative;
    min-height: 34px;
  }

  .meeting-main {
    flex: 1;
    padding-right: 34px;
  }

  .item-menu-wrap {
    position: absolute;
    right: 4px;
    top: 50%;
    transform: translateY(-50%);
    z-index: 20;
  }

  .item-menu-trigger {
    border: 1px solid #3a3a3a;
    background: transparent;
    color: #c7c7c7;
    border-radius: 8px;
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 0.95rem;
    opacity: 0;
    list-style: none;
    transition: opacity 0.14s ease;
  }

  .item-menu-trigger::-webkit-details-marker {
    display: none;
  }

  .meeting-row:hover .item-menu-trigger,
  .meeting-row:focus-within .item-menu-trigger,
  .item-menu-wrap[open] .item-menu-trigger {
    opacity: 1;
  }

  .item-menu-trigger:hover {
    background: #2b2b2b;
    color: #f3f4f6;
  }

  .item-menu {
    position: absolute;
    right: 0;
    top: 32px;
    min-width: 124px;
    background: #242424;
    border: 1px solid #3a3a3a;
    border-radius: 10px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    padding: 6px;
    z-index: 30;
    display: none;
    flex-direction: column;
    gap: 4px;
  }

  .item-menu-wrap[open] .item-menu {
    display: flex;
  }

  .item-menu button {
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
    color: rgba(255, 255, 255, 0.87);
    text-align: left;
    padding: 7px 8px;
    font-size: 0.82rem;
    cursor: pointer;
  }

  .item-menu button:hover {
    background: #2f2f2f;
  }

  .group-label {
    padding: 8px 10px;
    color: #c7c7c7;
    font-size: 0.86rem;
  }

  .chat-list {
    margin-top: 6px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 2px;
  }

  .chat-item {
    width: 100%;
    text-align: left;
    border: none;
    background: transparent;
    color: #c7c7c7;
    font-size: 0.85rem;
    padding: 8px 10px;
    border-radius: 8px;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .chat-item.active {
    background: #2f2f2f;
    color: #f3f4f6;
  }

  .auth-card {
    border: 1px solid #3a3a3a;
    border-radius: 12px;
    padding: 10px;
    background: #1f1f1f;
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 10px;
  }

  .auth-page {
    min-height: 100vh;
    width: 100%;
    background: #242424;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    box-sizing: border-box;
  }

  .auth-center-card {
    width: min(430px, 100%);
    border: 1px solid #3a3a3a;
    border-radius: 14px;
    background: #1a1a1a;
    padding: 18px;
    box-sizing: border-box;
    box-shadow: 0 16px 34px rgba(0, 0, 0, 0.35);
  }

  .auth-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }

  .auth-subtitle {
    margin: 0 0 12px;
    color: #a1a1aa;
    font-size: 0.85rem;
  }

  .auth-title {
    font-size: 0.88rem;
    color: #e5e7eb;
    font-weight: 600;
  }

  .auth-card input {
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    background: #161616;
    color: #f3f4f6;
    padding: 8px 9px;
    font-size: 0.84rem;
    font-family: inherit;
  }

  .auth-error {
    color: #fca5a5;
    font-size: 0.78rem;
  }

  .auth-actions {
    display: flex;
    gap: 8px;
  }

  .auth-button {
    flex: 1;
    border-radius: 8px;
    border: 1px solid #3a3a3a;
    background: #242424;
    color: #f3f4f6;
    padding: 7px 8px;
    font-size: 0.82rem;
    cursor: pointer;
  }

  .auth-toggle {
    border-radius: 8px;
    border: 1px solid #3a3a3a;
    background: transparent;
    color: #d1d5db;
    padding: 7px 8px;
    font-size: 0.78rem;
    cursor: pointer;
  }

  .helper-note {
    font-size: 0.78rem;
    color: #a1a1aa;
    margin: 4px 8px;
  }

  .chat-item:hover {
    background: #2b2b2b;
  }

  .sidebar-lists {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    margin-top: 4px;
    gap: 8px;
  }

  .sidebar-section {
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .meetings-section {
    flex: 2 1 0;
  }

  .chats-section {
    flex: 1 1 0;
  }

  .user-wrap {
    position: relative;
    margin-top: 10px;
  }

  .user-button {
    border: 1px solid #3a3a3a;
    background: #242424;
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }

  .initial-badge {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: #3b3b3b;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.78rem;
    font-weight: 700;
  }

  .user-name {
    font-size: 0.9rem;
  }

  .user-menu {
    position: absolute;
    left: 0;
    bottom: calc(100% + 8px);
    width: 100%;
    background: #242424;
    border: 1px solid #3a3a3a;
    border-radius: 12px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    padding: 6px;
    box-sizing: border-box;
    z-index: 10;
  }

  .user-menu button {
    cursor: pointer;
    color: rgba(255, 255, 255, 0.87);
  }

  .user-menu button:hover {
    background: #2f2f2f;
  }

  .main-content {
    flex: 1;
    min-width: 0;
    padding: 12px 16px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
  }

  .enrollment-wrapper {
    width: 100%;
    padding: 0 24px;
    box-sizing: border-box;
  }

  .enrollment-wrapper.new-meeting {
    margin-top: 28px;
  }

  .enrollment-wrapper.historical-meeting {
    margin-top: 24px;
  }

  .main-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
  }

  .main-body.with-meeting-chat {
    padding-bottom: 132px;
    box-sizing: border-box;
  }

  .main-body.chat-layout {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  .console-input,
  .console-select {
    border: 1px solid #3a3a3a;
    border-radius: 10px;
    background: #121212;
    color: #f3f4f6;
    padding: 10px 11px;
    font-size: 0.9rem;
    font-family: inherit;
  }

  .console-button {
    border-radius: 10px;
    font-family: inherit;
    cursor: pointer;
  }

  .console-button {
    border: 1px solid #4a4a4a;
    background: #f3f4f6;
    color: #111111;
    padding: 10px 14px;
    font-size: 0.88rem;
    font-weight: 600;
  }

  .settings-modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.58);
    backdrop-filter: blur(10px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    z-index: 120;
  }

  .settings-shell {
    width: min(920px, 100%);
    max-height: min(88vh, 920px);
    overflow: auto;
    border: 1px solid #313131;
    border-radius: 24px;
    background: #171717;
    box-shadow: 0 32px 80px rgba(0, 0, 0, 0.45);
  }

  .settings-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 22px 24px 18px;
    border-bottom: 1px solid #292929;
  }

  .settings-header-actions {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .settings-title {
    margin: 0;
    color: #f3f4f6;
    font-size: 1.65rem;
    font-weight: 650;
  }

  .settings-subtitle {
    margin: 6px 0 0;
    color: #9ca3af;
    font-size: 0.92rem;
  }

  .settings-panel {
    overflow: hidden;
  }

  .settings-group {
    padding: 10px 0;
    border-bottom: 1px solid #292929;
  }

  .settings-group:last-child {
    border-bottom: none;
  }

  .settings-group-head {
    padding: 10px 24px 6px;
  }

  .settings-group-head h3 {
    margin: 0;
    color: #e5e7eb;
    font-size: 0.84rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .settings-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 16px 24px;
  }

  .settings-row + .settings-row {
    border-top: 1px solid #232323;
  }

  .settings-row-tall {
    align-items: flex-start;
  }

  .settings-row-static {
    align-items: flex-start;
  }

  .settings-row-copy {
    min-width: 0;
  }

  .settings-row-title {
    color: #f3f4f6;
    font-size: 0.96rem;
    font-weight: 600;
  }

  .settings-row-desc {
    margin-top: 4px;
    color: #9ca3af;
    font-size: 0.86rem;
    line-height: 1.45;
    max-width: 62ch;
  }

  .settings-row-control {
    flex-shrink: 0;
    min-width: 220px;
    display: flex;
    justify-content: flex-end;
  }

  .settings-row-control .console-select {
    width: min(280px, 100%);
  }

  .settings-link-button {
    border: 1px solid #3a3a3a;
    border-radius: 999px;
    background: #1f1f1f;
    color: #f3f4f6;
    padding: 10px 14px;
    font-size: 0.86rem;
    font-family: inherit;
    cursor: pointer;
  }

  .settings-link-button:hover {
    background: #262626;
    border-color: #4b4b4b;
  }

  .settings-close-button {
    width: 36px;
    height: 36px;
    border: 1px solid #3a3a3a;
    border-radius: 999px;
    background: #1f1f1f;
    color: #e5e7eb;
    font-size: 1rem;
    line-height: 1;
    font-family: inherit;
    cursor: pointer;
  }

  .settings-close-button:hover {
    background: #262626;
    border-color: #4b4b4b;
  }

  .settings-footer {
    padding: 16px 24px 20px;
    border-top: 1px solid #292929;
  }

  :global(:root[data-theme='light']) .app-shell,
  :global(:root[data-theme='light']) .auth-page,
  :global(:root[data-theme='light']) .chat-mode-panel {
    background: #eef2f7;
    color: #111827;
  }

  :global(:root[data-theme='light']) .sidebar,
  :global(:root[data-theme='light']) .auth-center-card,
  :global(:root[data-theme='light']) .auth-card,
  :global(:root[data-theme='light']) .settings-shell,
  :global(:root[data-theme='light']) .chat-composer,
  :global(:root[data-theme='light']) .chat-mode-input-shell .chat-composer,
  :global(:root[data-theme='light']) .start-choice,
  :global(:root[data-theme='light']) .icon-button,
  :global(:root[data-theme='light']) .user-menu,
  :global(:root[data-theme='light']) .item-menu {
    background: #f8fafc;
    border-color: #d8e1eb;
    color: #111827;
  }

  :global(:root[data-theme='light']) .sidebar,
  :global(:root[data-theme='light']) .settings-header,
  :global(:root[data-theme='light']) .settings-group,
  :global(:root[data-theme='light']) .settings-footer,
  :global(:root[data-theme='light']) .item-menu button {
    border-color: #d8e1eb;
  }

  :global(:root[data-theme='light']) .user-menu button {
    border-color: #f8fafc;
    background: transparent;
  }

  :global(:root[data-theme='light']) .logo-row,
  :global(:root[data-theme='light']) .side-item,
  :global(:root[data-theme='light']) .side-pill,
  :global(:root[data-theme='light']) .user-button,
  :global(:root[data-theme='light']) .user-menu button,
  :global(:root[data-theme='light']) .item-menu button,
  :global(:root[data-theme='light']) .group-label,
  :global(:root[data-theme='light']) .helper-note,
  :global(:root[data-theme='light']) .chat-item,
  :global(:root[data-theme='light']) .settings-subtitle,
  :global(:root[data-theme='light']) .settings-row-desc,
  :global(:root[data-theme='light']) .chat-empty,
  :global(:root[data-theme='light']) .chat-loading {
    color: #475569;
  }

  :global(:root[data-theme='light']) .settings-title,
  :global(:root[data-theme='light']) .settings-row-title,
  :global(:root[data-theme='light']) .start-title,
  :global(:root[data-theme='light']) .start-choice-title,
  :global(:root[data-theme='light']) .chat-bubble.assistant,
  :global(:root[data-theme='light']) .chat-message-list,
  :global(:root[data-theme='light']) .model-select,
  :global(:root[data-theme='light']) .speaker-toggle label {
    color: #111827;
  }

  :global(:root[data-theme='light']) .chat-item.active,
  :global(:root[data-theme='light']) .meeting-row:hover .item-menu-trigger,
  :global(:root[data-theme='light']) .meeting-row:focus-within .item-menu-trigger,
  :global(:root[data-theme='light']) .item-menu-wrap[open] .item-menu-trigger,
  :global(:root[data-theme='light']) .logo-row:hover,
  :global(:root[data-theme='light']) .side-item:hover,
  :global(:root[data-theme='light']) .side-pill:hover,
  :global(:root[data-theme='light']) .item-menu button:hover,
  :global(:root[data-theme='light']) .user-menu button:hover,
  :global(:root[data-theme='light']) .settings-link-button:hover,
  :global(:root[data-theme='light']) .settings-close-button:hover,
  :global(:root[data-theme='light']) .chat-item:hover,
  :global(:root[data-theme='light']) .chat-mic:hover,
  :global(:root[data-theme='light']) .chat-send:hover,
  :global(:root[data-theme='light']) .icon-button:hover {
    background: #e9eef5;
    color: #111827;
  }

  :global(:root[data-theme='light']) .user-menu button:hover {
    border-color: #d8e1eb;
  }

  :global(:root[data-theme='light']) .chat-item.active {
    border-color: #d8e1eb;
  }

  :global(:root[data-theme='light']) .model-select,
  :global(:root[data-theme='light']) .auth-card input {
    background: #ffffff;
    border-color: #d8e1eb;
    color: #111827;
  }

  :global(:root[data-theme='light']) .auth-button,
  :global(:root[data-theme='light']) .auth-toggle,
  :global(:root[data-theme='light']) .settings-link-button,
  :global(:root[data-theme='light']) .settings-close-button,
  :global(:root[data-theme='light']) .chat-mic,
  :global(:root[data-theme='light']) .chat-send,
  :global(:root[data-theme='light']) .chat-minimized-button,
  :global(:root[data-theme='light']) .item-menu-trigger,
  :global(:root[data-theme='light']) .user-button {
    background: #f8fafc;
    border-color: #d8e1eb;
    color: #111827;
  }

  :global(:root[data-theme='light']) .chat-bubble.user {
    background: #e6edf6;
    border-color: #d3deea;
    color: #111827;
  }

  :global(:root[data-theme='light']) .settings-modal-backdrop {
    background: rgba(148, 163, 184, 0.35);
  }

  :global(:root[data-theme='light']) .console-input,
  :global(:root[data-theme='light']) .console-select {
    background: #ffffff;
    border-color: #d8e1eb;
    color: #111827;
  }

  :global(:root[data-theme='light']) .chat-mode-input-wrap.docked {
    background: linear-gradient(to top, rgba(238, 242, 247, 0.96) 76%, rgba(238, 242, 247, 0));
  }

  :global(:root[data-theme='light']) .chat-mode-input-shell .chat-composer,
  :global(:root[data-theme='light']) .chat-composer {
    background: #f8fafc;
    border-color: #d8e1eb;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
  }

  :global(:root[data-theme='light']) .chat-composer textarea {
    color: #111827;
  }

  :global(:root[data-theme='light']) .chat-composer textarea::placeholder {
    color: #64748b;
  }

  :global(:root[data-theme='light']) .chat-bubble.pending {
    color: #475569;
  }

  :global(:root[data-theme='light']) .logo-badge,
  :global(:root[data-theme='light']) .initial-badge {
    background: #dbe4f0;
    color: #0f172a;
  }

  @media (max-width: 900px) {
    .settings-header,
    .settings-row {
      flex-direction: column;
      align-items: flex-start;
    }

    .settings-header-actions {
      width: 100%;
      justify-content: space-between;
    }

    .settings-row-control {
      width: 100%;
      min-width: 0;
      justify-content: flex-start;
    }

    .settings-row-control .console-select {
      width: 100%;
    }
  }

  .chat-mode-panel {
    width: 100%;
    margin: 0 auto;
    background: #242424;
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    position: relative;
    border-radius: 12px;
  }

  .chat-mode-header {
    display: none;
  }

  .chat-mode-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 18px 14px 10px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .chat-mode-panel.docked .chat-mode-body {
    padding-bottom: 96px;
  }

  .chat-mode-body.center-empty {
    justify-content: flex-end;
    align-items: center;
    text-align: center;
    color: #a3a3a3;
    padding-bottom: 20px;
  }

  .chat-agent-hero {
    width: min(760px, 100%);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    margin-top: 18px;
  }

  .chat-agent-title {
    color: #f3f4f6;
    font-size: clamp(1.7rem, 2.4vw, 2.3rem);
    font-weight: 600;
    letter-spacing: -0.02em;
    line-height: 1.05;
  }

  .chat-agent-copy {
    color: #9ca3af;
    font-size: 0.96rem;
    line-height: 1.45;
    max-width: 72ch;
  }

  .chat-agent-launch-wrap {
    margin-top: 12px;
    display: flex;
    justify-content: center;
  }

  .chat-agent-launch {
    width: min(410px, 100%);
    height: min(152px, 50%);
    aspect-ratio: 1 / 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    text-align: center;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid #353535;
    border-radius: 16px;
    padding: 20px;
    cursor: pointer;
    transition: border-color 0.13s ease, background 0.13s ease, transform 0.13s ease;
  }

  .chat-agent-launch:hover,
  .chat-agent-launch:focus-visible {
    border-color: #5b5b5b;
    background: rgba(255, 255, 255, 0.05);
    transform: translateY(-1px);
    outline: none;
  }

  .chat-agent-launch-title {
    color: #f3f4f6;
    font-size: 0.95rem;
    font-weight: 600;
  }

  .chat-agent-launch-copy {
    color: #a3a3a3;
    font-size: 0.86rem;
    line-height: 1.45;
  }

  :global(:root[data-theme='light']) .chat-agent-title {
    color: #111827;
  }

  :global(:root[data-theme='light']) .chat-agent-copy {
    color: #6b7280;
  }

  :global(:root[data-theme='light']) .chat-agent-launch {
    border-color: #e5e7eb;
    background: #ffffff;
  }

  :global(:root[data-theme='light']) .chat-agent-launch-title {
    color: #111827;
  }

  :global(:root[data-theme='light']) .chat-agent-launch-copy {
    color: #6b7280;
  }

  .chat-bubble {
    max-width: min(78ch, 90%);
    border-radius: 16px;
    padding: 12px 14px;
    white-space: pre-wrap;
    word-break: break-word;
    color: #e5e7eb;
    font-size: 0.95rem;
    line-height: 1.45;
  }

  .chat-bubble.user {
    margin-left: auto;
    background: #303030;
    border: 1px solid #3e3e3e;
  }

  .chat-bubble.assistant {
    margin-right: auto;
    background: transparent;
    border: 1px solid transparent;
    padding-left: 2px;
  }

  .chat-bubble.pending {
    color: #cbd5e1;
  }

  .chat-bubble.error {
    color: #fecaca;
    background: rgba(127, 29, 29, 0.22);
    border-color: rgba(248, 113, 113, 0.4);
    padding: 12px 14px;
  }

  /* --- Agent action card --- */
  .action-cards-wrap {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    width: 100%;
    padding-left: 2px;
  }

  .action-card-row {
    display: flex;
    width: auto;
  }

  .action-card-row.dismiss-row {
    width: 100%;
    padding-left: 2px;
    margin-top: 8px;
  }

  .action-card {
    display: inline-flex;
    align-items: center;
    gap: 14px;
    background: rgba(99, 102, 241, 0.08);
    border: 1px solid rgba(99, 102, 241, 0.32);
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 0.88rem;
    color: #c7d0ff;
    max-width: 480px;
  }

  .action-card-label {
    flex: 1;
  }

  .action-card-buttons {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
  }

  .action-select {
    background: rgba(33, 33, 48, 0.9);
    color: #d8ddff;
    border: 1px solid #40446d;
    border-radius: 7px;
    padding: 5px 10px;
    font-size: 0.83rem;
    min-width: 220px;
  }

  .action-confirm {
    background: rgba(99, 102, 241, 0.75);
    color: #fff;
    border: none;
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 0.83rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.14s ease;
  }

  .action-confirm:hover {
    background: rgba(99, 102, 241, 1);
  }

  .action-dismiss {
    background: transparent;
    color: #8b8da0;
    border: 1px solid #3a3a3a;
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 0.83rem;
    cursor: pointer;
    transition: color 0.14s ease, border-color 0.14s ease;
  }

  .action-dismiss:hover {
    color: #c7c7c7;
    border-color: #555;
  }

  :global(:root[data-theme='light']) .action-card {
    background: rgba(99, 102, 241, 0.06);
    border-color: rgba(99, 102, 241, 0.3);
    color: #3730a3;
  }

  :global(:root[data-theme='light']) .action-confirm {
    background: rgba(99, 102, 241, 0.85);
  }

  :global(:root[data-theme='light']) .action-dismiss {
    border-color: #ccc;
    color: #666;
  }

  :global(:root[data-theme='light']) .action-dismiss:hover {
    color: #333;
    border-color: #999;
  }

  :global(:root[data-theme='light']) .action-select {
    background: #fff;
    color: #1f2937;
    border-color: #cbd5e1;
  }
  /* --- end action card --- */

  .thinking-indicator {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    min-height: 24px;
  }

  .thinking-label {
    letter-spacing: 0.01em;
  }

  .thinking-dots {
    display: inline-flex;
    gap: 5px;
    align-items: center;
  }

  .thinking-dots span {
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: currentColor;
    opacity: 0.28;
    animation: thinking-blink 1.1s infinite ease-in-out;
  }

  .thinking-dots span:nth-child(2) {
    animation-delay: 0.18s;
  }

  .thinking-dots span:nth-child(3) {
    animation-delay: 0.36s;
  }

  .chat-empty,
  .chat-loading {
    color: #a3a3a3;
    font-size: 0.92rem;
  }

  .chat-message-list {
    width: min(860px, 100%);
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .chat-row {
    display: flex;
    width: 100%;
  }

  .chat-row.user {
    justify-content: flex-end;
  }

  .chat-row.assistant {
    justify-content: flex-start;
  }

  .chat-mode-input-wrap {
    padding: 10px 14px 14px;
    background: transparent;
  }

  .chat-mode-input-wrap.docked {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 8px 14px 8px;
    background: linear-gradient(to top, rgba(36, 36, 36, 1) 76%, rgba(36, 36, 36, 0));
  }

  .chat-mode-input-wrap.centered {
    border-top: none;
    background: transparent;
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 10px 18px 18px;
  }

  .chat-mode-input-shell {
    width: min(860px, 100%);
    margin: 0 auto;
  }

  .chat-mode-input-shell.compact .chat-composer {
    min-height: 64px;
    padding: 8px 10px;
    border-radius: 24px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.24);
  }

  .chat-mode-input-shell.compact .chat-composer textarea {
    min-height: 28px;
    max-height: 120px;
  }

  .start-shell {
    width: min(760px, 100%);
    height: 100%;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 10px;
  }

  .start-title {
    margin: 0;
    color: #f3f4f6;
    font-size: 1.28rem;
    font-weight: 650;
  }

  .start-subtitle {
    margin: 0;
    color: #a3a3a3;
    font-size: 0.9rem;
  }

  .start-choices {
    margin-top: 10px;
    width: 100%;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .start-choice {
    border: 1px solid #3a3a3a;
    border-radius: 14px;
    background: #1a1a1a;
    color: #e5e7eb;
    padding: 16px 14px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    text-align: left;
    cursor: pointer;
    font-family: inherit;
  }

  .start-choice:hover {
    background: #212121;
    border-color: #4a4a4a;
  }

  .start-choice-icon {
    font-size: 1.1rem;
    line-height: 1;
  }

  .start-choice-title {
    font-size: 0.98rem;
    font-weight: 600;
    color: #f3f4f6;
  }

  .start-choice-note {
    font-size: 0.82rem;
    color: #a3a3a3;
  }

  .actions-layout {
    width: min(980px, 100%);
    margin: 8px auto 28px;
  }

  .model-row {
    display: flex;
    justify-content: flex-start;
    margin: 2px 0 12px;
  }

  .model-select {
    min-width: 240px;
    border-radius: 8px;
    border: none;
    background: #242424;
    color: rgba(255, 255, 255, 0.87);
    padding: 8px 10px;
    font-size: 1.02rem;
    font-weight: 700;
    font-family: inherit;
    box-shadow: none;
    outline: none;
  }

  .actions {
    display: flex;
    justify-content: center;
    gap: 1rem;
    margin: 0;
    flex-wrap: wrap;
  }

  .icon-button {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    background: #1a1a1a;
    border: 1px solid #3a3a3a;
    border-radius: 12px;
    padding: 1rem 1.2rem;
    min-width: 220px;
    cursor: pointer;
    color: #fff;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.04);
    transition: background 0.2s, transform 0.15s, border-color 0.2s, box-shadow 0.2s;
  }

  .icon-button:hover {
    background: #222222;
    border-color: #4a4a4a;
    transform: translateY(-1px);
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  }

  .icon-button svg {
    width: 40px;
    height: 40px;
    margin-bottom: 0.5rem;
    transition: color 0.3s;
  }

  .speaker-toggle {
    display: flex;
    justify-content: flex-end;
    margin: 0 0 0.8rem;
  }

  .speaker-toggle label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: #ffffff;
    font-size: 0.95rem;
  }

  /* flashing red animation */
  .recording svg {
    animation: pulseRed 3s infinite;
  }

  @keyframes pulseRed {
    0%, 50%, 100% { color: #ff0000; }
    25%, 75% { color: #fff; }
  }

  .chat-composer-wrap {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: min(760px, calc(100% - 48px));
    display: flex;
    justify-content: center;
    background: transparent;
    z-index: 20;
  }

  .chat-composer-wrap.in-meeting {
    top: auto;
    left: auto;
    right: 18px;
    bottom: 16px;
    transform: none;
    width: min(440px, calc(100% - 32px));
    z-index: 30;
  }

  .chat-composer-wrap.minimized {
    width: auto;
  }

  .chat-composer {
    width: 100%;
    border: 1px solid #353535;
    border-radius: 16px;
    background: #1a1a1a;
    min-height: 132px;
    padding: 16px 16px;
    box-sizing: border-box;
    display: flex;
    gap: 10px;
    align-items: center;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.28);
  }

  .chat-mode-input-shell .chat-composer {
    border-radius: 24px;
    min-height: 112px;
    padding: 12px 14px;
    background: #1f1f1f;
    border-color: #3b3b3b;
  }

  .chat-composer-wrap.in-meeting .chat-composer {
    min-height: 98px;
    padding: 12px;
    border-radius: 14px;
  }

  .chat-minimized-button {
    border: 1px solid #3a3a3a;
    background: #1a1a1a;
    color: rgba(255, 255, 255, 0.9);
    border-radius: 12px;
    padding: 8px 12px;
    font-size: 0.86rem;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
  }

  .chat-minimized-button svg {
    width: 15px;
    height: 15px;
    fill: currentColor;
  }

  .chat-minimized-button:hover {
    background: #232323;
    border-color: #4a4a4a;
  }

  .chat-composer textarea {
    flex: 1;
    min-height: 104px;
    max-height: 240px;
    border: none;
    background: transparent;
    color: rgba(255, 255, 255, 0.9);
    resize: none;
    outline: none;
    font-family: inherit;
    font-size: 0.93rem;
    position: relative;
    z-index: 1;
  }

  .chat-composer {
    position: relative;
  }

  .voice-inline-status {
    position: absolute;
    left: 56px;
    right: 56px;
    top: 16px;
    color: #e5e7eb;
    opacity: 0.82;
    font-size: 0.9rem;
    pointer-events: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    z-index: 2;
  }

  .voice-inline-status.error {
    color: #fca5a5;
  }

  .chat-mic,
  .chat-send {
    width: 34px;
    height: 34px;
    border-radius: 999px;
    border: 1px solid #3b3b3b;
    background: #202020;
    color: #d1d5db;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    cursor: pointer;
  }

  .chat-mic svg,
  .chat-send svg {
    width: 16px;
    height: 16px;
    fill: currentColor;
  }

  .chat-mic:hover,
  .chat-send:hover {
    color: #ffffff;
    border-color: #5a5a5a;
    background: #252525;
  }

  .chat-send:disabled {
    cursor: default;
    opacity: 0.58;
  }

  .chat-send:disabled:hover {
    color: #d1d5db;
    border-color: #3b3b3b;
    background: #202020;
  }

  .chat-mic.recording {
    color: #ef4444;
    border-color: #dc2626;
    background: #7f1d1d;
    animation: pulse-record 1.5s infinite;
  }

  @keyframes pulse-record {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.7;
    }
  }

  @keyframes thinking-blink {
    0%,
    80%,
    100% {
      opacity: 0.25;
      transform: translateY(0);
    }

    40% {
      opacity: 1;
      transform: translateY(-1px);
    }
  }
</style>

{#if !authenticated}
<main class="auth-page">
  <div class="auth-center-card">
    <div class="auth-header">
      <span class="logo-badge">OM</span>
      <span>Open Meet Sum</span>
    </div>
    <p class="auth-subtitle">{authMode === 'login' ? 'Sign in to access your workspace.' : 'Create an account to get started.'}</p>
    <div class="auth-card">
      <div class="auth-title">{authMode === 'login' ? 'Sign in' : 'Create account'}</div>
      <input type="email" bind:value={authEmail} placeholder="Email" />
      <input type="password" bind:value={authPassword} placeholder="Password" />
      {#if authMode === 'register'}
        <input type="text" bind:value={authUsername} placeholder="Username (optional)" />
        <input type="text" bind:value={authDisplayName} placeholder="Display name (optional)" />
      {/if}
      {#if authError}
        <div class="auth-error">{authError}</div>
      {/if}
      <div class="auth-actions">
        <button class="auth-button" type="button" on:click={submitAuth} disabled={authLoading}>
          {authLoading ? 'Please wait...' : authMode === 'login' ? 'Login' : 'Register'}
        </button>
        <button class="auth-toggle" type="button" on:click={() => (authMode = authMode === 'login' ? 'register' : 'login')}>
          {authMode === 'login' ? 'Need account?' : 'Have account?'}
        </button>
      </div>
    </div>
  </div>
</main>
{:else}
<div class="app-shell" on:click={closeUserMenu}>
  <aside class="sidebar" on:click|stopPropagation>
    <button class="logo-row" type="button" on:click={goToFrontPage}>
      <span class="logo-badge">OM</span>
      <span>Open Meet Sum</span>
    </button>

    <button class="side-item" type="button" on:click={openMeetingOptions}>
      <span class="side-item-icon">🎤</span>
      <span>New meeting</span>
    </button>
    <button class="side-item" type="button" on:click={createNewChat}>
      <span class="side-item-icon">＋</span>
      <span>New chat</span>
    </button>
    <button class="side-pill" type="button">
      <span class="side-pill-icon">⌕</span>
      <span>Search</span>
    </button>
    <button class="side-pill" type="button">
      <span class="side-pill-icon">📝</span>
      <span>Notes</span>
    </button>
    <button class="side-pill" type="button">
      <span class="side-pill-icon">▦</span>
      <span>Workspaces</span>
    </button>

    <div class="sidebar-lists">
      <div class="sidebar-section meetings-section">
        <div class="section-label">Meetings</div>
        <div class="meeting-group os-scroll">
          {#if meetingItems.length}
            {#each meetingItems as meeting}
              <div class="meeting-row">
                <button
                  class="chat-item meeting-main"
                  class:active={meeting.id === activeMeetingId}
                  type="button"
                  on:click={() => openMeeting(meeting.id)}
                  title="Open meeting"
                >
                  {meeting.title}
                </button>
                <details class="item-menu-wrap" on:click|stopPropagation on:toggle={handleItemMenuToggle}>
                  <summary class="item-menu-trigger" title="More">⋯</summary>
                  <div class="item-menu" on:click|stopPropagation>
                    <button type="button" on:click={() => renameMeeting(meeting)}>Rename</button>
                    <button type="button" on:click={() => deleteMeeting(meeting.id)}>Delete</button>
                  </div>
                </details>
              </div>
            {/each}
          {:else}
            <div class="group-label">No meetings yet</div>
          {/if}
        </div>
      </div>

      <div class="sidebar-section chats-section">
        <div class="section-label">Chats</div>
        <div class="chat-list os-scroll">
          {#if chatItems.length}
            {#each chatItems as chat}
              <div class="meeting-row">
                <button
                  class="chat-item meeting-main"
                  class:active={chat.id === activeChatId}
                  type="button"
                  on:click={() => openChat(chat.id)}
                  title="Open chat"
                >
                  {chat.title}
                </button>
                <details class="item-menu-wrap" on:click|stopPropagation on:toggle={handleItemMenuToggle}>
                  <summary class="item-menu-trigger" title="More">⋯</summary>
                  <div class="item-menu" on:click|stopPropagation>
                    <button type="button" on:click={() => renameChat(chat)}>Rename</button>
                    <button type="button" on:click={() => deleteChat(chat.id)}>Delete</button>
                  </div>
                </details>
              </div>
            {/each}
          {:else}
            <div class="helper-note">No chats yet</div>
          {/if}
        </div>
      </div>
    </div>

    <div class="user-wrap">
      {#if showUserMenu}
        <div class="user-menu">
          <button type="button" on:click={() => openUserView('settings')}>Settings</button>
          {#if currentUser?.is_superuser}
            <button type="button" on:click={() => openUserView('admin')}>Admin panel</button>
          {/if}
          <button type="button" on:click={() => openUserView('account')}>Account</button>
          <button type="button" on:click={logout}>Sign out</button>
        </div>
      {/if}
      <button class="user-button" type="button" on:click={toggleUserMenu}>
        <span class="initial-badge">{getInitials()}</span>
        <span class="user-name">{getDisplayName()}</span>
      </button>
    </div>
  </aside>

  <main class="main-content">
<div class="main-body os-scroll" class:chat-layout={mode === 'chat'} class:with-meeting-chat={mode === 'record' || mode === 'upload'}>
{#if mode === 'chat'}
  <div class="chat-mode-panel" class:docked={chatDocked}>
    {#if chatDocked}
      <div class="chat-mode-header">Chat</div>
      <div class="chat-mode-body os-scroll" bind:this={chatScrollEl}>
        {#if chatLoading}
          <div class="chat-message-list">
            <div class="chat-loading">Loading messages...</div>
          </div>
        {:else if !chatMessages.length}
          <div class="chat-message-list">
            <div class="chat-empty">{chatError || 'No messages yet. Ask anything to start this chat.'}</div>
          </div>
        {:else}
          <div class="chat-message-list">
            {#each chatMessages as msg}
              <div class="chat-row {msg.role === 'assistant' ? 'assistant' : 'user'}">
                <div class="chat-bubble {msg.role === 'assistant' ? 'assistant' : 'user'}" class:pending={msg.pending} class:error={msg.error}>
                  {#if msg.pending}
                    <span class="thinking-indicator" aria-label="Assistant is thinking">
                      <span class="thinking-label">Thinking</span>
                      <span class="thinking-dots" aria-hidden="true">
                        <span></span>
                        <span></span>
                        <span></span>
                      </span>
                    </span>
                  {:else}
                    {msg.content}
                  {/if}
                </div>
              </div>
            {/each}
            {#if pendingActions.length}
              <div class="action-cards-wrap">
                {#each regularPendingActions as action}
                  <div class="action-card-row">
                    <div class="action-card">
                      <span class="action-card-label">{action.label}</span>
                      <div class="action-card-buttons">
                        <button class="action-confirm" type="button" on:click={() => void executeAction(action)}>Go</button>
                      </div>
                    </div>
                  </div>
                {/each}
                {#if sidebarLabelActions.length}
                  <div class="action-card-row">
                    <div class="action-card">
                      <span class="action-card-label">Display name</span>
                      <div class="action-card-buttons">
                        <select class="action-select" bind:value={selectedSidebarLabelActionType}>
                          {#each sidebarLabelActions as action}
                            <option value={action.type}>{action.label}</option>
                          {/each}
                        </select>
                        <button class="action-confirm" type="button" on:click={() => executeActionByType(selectedSidebarLabelActionType)}>Go</button>
                      </div>
                    </div>
                  </div>
                {/if}
                {#if themeActions.length}
                  <div class="action-card-row">
                    <div class="action-card">
                      <span class="action-card-label">Theme</span>
                      <div class="action-card-buttons">
                        <select class="action-select" bind:value={selectedThemeActionType}>
                          {#each themeActions as action}
                            <option value={action.type}>{action.label}</option>
                          {/each}
                        </select>
                        <button class="action-confirm" type="button" on:click={() => executeActionByType(selectedThemeActionType)}>Go</button>
                      </div>
                    </div>
                  </div>
                {/if}
                {#if languageActions.length}
                  <div class="action-card-row">
                    <div class="action-card">
                      <span class="action-card-label">Language settings</span>
                      <div class="action-card-buttons">
                        <select class="action-select" bind:value={selectedLanguageActionValue}>
                          {#each appLanguageOptions as option}
                            <option value={`app:${option.value}`}>App language: {option.label}</option>
                          {/each}
                          {#each whisperLanguageOptions as option}
                            <option value={`spoken:${option.value}`}>Spoken language: {option.label}</option>
                          {/each}
                        </select>
                        <button class="action-confirm" type="button" on:click={() => void executeLanguageActionSelection()}>Go</button>
                      </div>
                    </div>
                  </div>
                {/if}
              </div>
              <div class="action-card-row dismiss-row">
                <button class="action-dismiss" type="button" on:click={dismissAction}>Hide options</button>
              </div>
            {:else if hiddenActions.length}
              <div class="action-card-row dismiss-row">
                <button class="action-dismiss" type="button" on:click={showHiddenActions}>Show options</button>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {:else}
      <div class="chat-mode-body center-empty">
        <div class="chat-agent-hero">
          <h2 class="chat-agent-title">MeetSum agent</h2>
          <p class="chat-agent-copy">I'm your personal MeetSum agent. Ask me to perform actions in MeetSum, or just start a general chat.</p>
        </div>
      </div>
    {/if}

    <div class="chat-mode-input-wrap" class:centered={!chatDocked} class:docked={chatDocked}>
      <div class="chat-mode-input-shell compact">
        <div class="chat-composer">
          <button class="chat-mic" type="button" aria-label="Voice input" on:click={handleVoiceMicToggle} class:recording={isVoiceRecording}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3z"></path>
              <path d="M18 11a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.91V20H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-3.09A6 6 0 0 0 18 11z"></path>
            </svg>
          </button>
          <textarea
            bind:this={chatInputEl}
            bind:value={chatInput}
            placeholder={getVoiceAwarePlaceholder('Instruct me to perform actions in MeetSum, or just ask me anything.')}
            on:keydown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submitChatPlaceholder();
              }
            }}
          ></textarea>
          {#if !chatInput.trim() && (isVoiceRecording || voiceTranscript || voiceError)}
            <div class="voice-inline-status" class:error={Boolean(voiceError) && !isVoiceRecording && !voiceTranscript}>
              {getVoiceInlineStatus()}
            </div>
          {/if}
          <button class="chat-send" type="button" aria-label="Send chat message" on:click={submitChatPlaceholder} disabled={isSendingMessage}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3.4 20.4L21 12 3.4 3.6 3.3 10l11.2 2-11.2 2z"></path>
            </svg>
          </button>
        </div>
      </div>
      {#if !chatDocked}
        <div class="chat-agent-launch-wrap">
          <div
            class="chat-agent-launch"
            role="button"
            tabindex="0"
            on:click={startAgentIntro}
            on:keydown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                startAgentIntro();
              }
            }}
          >
            <div class="chat-agent-launch-title">See what I can help you with</div>
            <div class="chat-agent-launch-copy">Get an in-chat overview of what I can do in MeetSum and which safe actions I can propose.</div>
          </div>
        </div>
      {/if}
    </div>
  </div>
{:else if mode === 'admin'}
  <AdminPanel {authToken} {currentUser} />
{:else}
{#if mode === 'none'}
  <div class="start-shell">
    <h2 class="start-title">What do you want to do?</h2>
    <p class="start-subtitle">Choose one to begin.</p>
    <div class="start-choices">
      <button class="start-choice" type="button" on:click={openMeetingOptions}>
        <span class="start-choice-icon">🎤</span>
        <span class="start-choice-title">Start meeting</span>
        <span class="start-choice-note">Record live and generate notes</span>
      </button>
      <button class="start-choice" type="button" on:click={openChatInterfaceFromIntro}>
        <span class="start-choice-icon">💬</span>
        <span class="start-choice-title">Start chat</span>
        <span class="start-choice-note">Ask questions and iterate quickly</span>
      </button>
    </div>
  </div>
{:else}
  {#if !isHistoricalMeeting}
    <div class="actions-layout">
      {#if mode !== 'none' && mode !== 'chat'}
        <div class="speaker-toggle">
          <label>
            <input type="checkbox" bind:checked={enableSpeakers} />
            Enable speaker labels
          </label>
        </div>
      {/if}

      <div class="actions">
        {#if isPaused}
          <div class="icon-button" class:recording={isPaused} on:click={selectRecord}>
            <svg viewBox="0 0 24 24" fill="rgb(255,255,255)" stroke="#ffffff">
              <path d="M12 21H15M12 21H9M12 21V18M12 18C8 18 5.5 15.3137 5.5 12M12 18C12.7167 18 13.3853 17.9137 14 17.7531M18.5 12C18.5 12.7013 18.388 13.3744 18.1736 14M3 3L21 21M9.16324 5C9.66075 3.86929 10.5214 3 12 3C15.1718 3 15.5 7 15.5 9C15.5 9.5553 15.4747 10.2648 15.3703 11"></path>
            </svg>
            Paused
          </div>
        {:else}
          <div class="icon-button" class:recording={isRecording} on:click={selectRecord}>
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3z"></path>
              <path d="M19 11a1 1 0 0 1-2 0 5 5 0 0 1-10 0 1 1 0 0 1-2 0 7 7 0 0 0 6 6.93V21a1 1 0 0 0 2 0v-3.07A7 7 0 0 0 19 11z"></path>
            </svg>
            Record
          </div>
        {/if}

        <div class="icon-button" on:click={selectUpload}>
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M5 20h14v-2H5v2z"></path>
            <path d="M12 16l4-5h-3V4h-2v7H8l4 5z"></path>
          </svg>
          Upload
        </div>
      </div>
    </div>
  {/if}

  {#if !isHistoricalMeeting}
    <div class="enrollment-wrapper new-meeting">
      {#if enableSpeakers}
        <SpeakerEnrollment
          bind:enrollmentFinalized={enrollmentFinalized}
          bind:attendees={meetingAttendees}
          on:attendeesChanged={handleAttendeesChanged}
          on:attendeesFinalized={handleAttendeesFinalized}
        />
      {:else}
        <SpeakerEnrollment enrollmentFinalized={true} historicalView={true} historicalAttendees={[]} />
      {/if}
    </div>
  {:else}
    <div class="enrollment-wrapper historical-meeting">
      <SpeakerEnrollment enrollmentFinalized={true} historicalView={true} historicalAttendees={meetingAttendees} />
    </div>
  {/if}

  {#if mode === 'record'}
  <LiveTranscriber
    bind:this={liveTranscriberComponent}
    bind:isRecording={isRecording}
    bind:isPaused={isPaused}
    on:meetingSaved={fetchSidebarData}
    {enableSpeakers}
    attendees={meetingAttendees}
  />
  {:else if mode === 'upload'}
    <UploadedAudio initialMeeting={activeMeetingPayload} attendees={meetingAttendees} {enableSpeakers} on:meetingSaved={fetchSidebarData} />
  {/if}
{/if}
{/if}
</div>

{#if mode === 'record' || mode === 'upload'}
<div class="chat-composer-wrap" class:in-meeting={mode === 'record' || mode === 'upload'} class:minimized={(mode === 'record' || mode === 'upload') && chatMinimized}>
  {#if mode !== 'none' && chatMinimized}
    <button class="chat-minimized-button" type="button" on:click={toggleChatMinimized}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3z"></path>
        <path d="M18 11a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.91V20H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-3.09A6 6 0 0 0 18 11z"></path>
      </svg>
      Chat
    </button>
  {:else}
  <div class="chat-composer">
    <button class="chat-mic" type="button" aria-label="Voice input" on:click={handleVoiceMicToggle} class:recording={isVoiceRecording}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3z"></path>
        <path d="M18 11a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.91V20H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-3.09A6 6 0 0 0 18 11z"></path>
      </svg>
    </button>
    <textarea
      bind:value={chatInput}
      placeholder={getVoiceAwarePlaceholder('Message Open Meet Sum...')}
      on:keydown={(event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          submitChatPlaceholder();
        }
      }}
    ></textarea>
    {#if !chatInput.trim() && (isVoiceRecording || voiceTranscript || voiceError)}
      <div class="voice-inline-status" class:error={Boolean(voiceError) && !isVoiceRecording && !voiceTranscript}>
        {getVoiceInlineStatus()}
      </div>
    {/if}
    <button class="chat-send" type="button" aria-label="Send chat placeholder" on:click={submitChatPlaceholder} disabled={isSendingMessage}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3.4 20.4L21 12 3.4 3.6 3.3 10l11.2 2-11.2 2z"></path>
      </svg>
    </button>
    {#if mode === 'record' || mode === 'upload'}
      <button class="chat-send" type="button" aria-label="Minimize chat" on:click={toggleChatMinimized}>−</button>
    {/if}
  </div>
  {/if}
</div>
{/if}
  </main>
</div>

{#if showSettingsModal}
  <div
    class="settings-modal-backdrop"
    role="button"
    tabindex="0"
    aria-label="Close settings"
    on:click={closeSettingsModal}
    on:keydown={(event) => {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Escape') {
        event.preventDefault();
        closeSettingsModal();
      }
    }}
  >
    <div
      class="settings-shell os-scroll"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-modal-title"
      tabindex="-1"
      on:click|stopPropagation
      on:keydown|stopPropagation
    >
      <div class="settings-header">
        <div>
          <h2 class="settings-title" id="settings-modal-title">Settings</h2>
          <p class="settings-subtitle">Application preferences for MeetSum.</p>
        </div>
        <div class="settings-header-actions">
          <button class="console-button" type="button" on:click={saveAppSettings} disabled={settingsSaving || settingsLoading}>
            {settingsSaving ? 'Saving...' : 'Save'}
          </button>
          <button class="settings-close-button" type="button" aria-label="Close settings" on:click={closeSettingsModal}>✕</button>
        </div>
      </div>

      <div class="settings-panel">
        {#if settingsLoading}
          <div class="settings-footer">
            <div class="console-status">Loading settings...</div>
          </div>
        {/if}
        <section class="settings-group">
          <div class="settings-group-head">
            <h3>General</h3>
          </div>
          <div class="settings-row">
            <div class="settings-row-copy">
              <div class="settings-row-title">Theme</div>
              <div class="settings-row-desc">Choose how the application should appear.</div>
            </div>
            <div class="settings-row-control">
              <select class="console-select" bind:value={appSettings.theme}>
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </div>
          </div>
          <div class="settings-row">
            <div class="settings-row-copy">
              <div class="settings-row-title">Language</div>
              <div class="settings-row-desc">User interface language. English is the only supported language for now.</div>
            </div>
            <div class="settings-row-control">
              <select class="console-select" bind:value={appSettings.language}>
                <option value="en">English</option>
              </select>
            </div>
          </div>
        </section>

        <section class="settings-group">
          <div class="settings-group-head">
            <h3>Audio</h3>
          </div>
          <div class="settings-row settings-row-tall">
            <div class="settings-row-copy">
              <div class="settings-row-title">Spoken language</div>
              <div class="settings-row-desc">Select Auto-detect or lock transcription to one of the languages Whisper can recognize.</div>
            </div>
            <div class="settings-row-control">
              <select class="console-select" bind:value={appSettings.spokenLanguage}>
                {#each whisperLanguageOptions as option}
                  <option value={option.value}>{option.label}</option>
                {/each}
              </select>
            </div>
          </div>
        </section>

        <section class="settings-group">
          <div class="settings-group-head">
            <h3>About</h3>
          </div>
          <div class="settings-row settings-row-static">
            <div class="settings-row-copy">
              <div class="settings-row-title">Version</div>
              <div class="settings-row-desc">MeetSum v{APP_VERSION}</div>
            </div>
          </div>
          <div class="settings-row settings-row-static">
            <div class="settings-row-copy">
              <div class="settings-row-title">Description</div>
              <div class="settings-row-desc">Meeting transcription, speaker-aware summarization, and follow-up chat in one workspace.</div>
            </div>
          </div>
          <div class="settings-row settings-row-static">
            <div class="settings-row-copy">
              <div class="settings-row-title">Copyright</div>
              <div class="settings-row-desc">Copyright (c) 2026 MeetSum. All rights reserved.</div>
            </div>
          </div>
        </section>

        <section class="settings-group">
          <div class="settings-group-head">
            <h3>Account</h3>
          </div>
          <div class="settings-row">
            <div class="settings-row-copy">
              <div class="settings-row-title">Account settings</div>
              <div class="settings-row-desc">Open your account page to manage username, display name, and session details.</div>
            </div>
            <div class="settings-row-control">
              <button class="settings-link-button" type="button" on:click={() => { closeSettingsModal(); void openUserView('account'); }}>Open account</button>
            </div>
          </div>
        </section>

        {#if settingsNotice || settingsError}
          <div class="settings-footer">
            {#if settingsNotice}
              <div class="console-status success">{settingsNotice}</div>
            {/if}
            {#if settingsError}
              <div class="console-status error">{settingsError}</div>
            {/if}
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}

{#if showAccountModal}
  <div
    class="settings-modal-backdrop"
    role="button"
    tabindex="0"
    aria-label="Close account"
    on:click={closeAccountModal}
    on:keydown={(event) => {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Escape') {
        event.preventDefault();
        closeAccountModal();
      }
    }}
  >
    <div
      class="settings-shell"
      role="dialog"
      aria-modal="true"
      aria-labelledby="account-modal-title"
      tabindex="-1"
      on:click|stopPropagation
      on:keydown|stopPropagation
    >
      <div class="settings-header">
        <div>
          <h2 class="settings-title" id="account-modal-title">Account</h2>
          <p class="settings-subtitle">Manage the identity and session details used across your workspace.</p>
        </div>
        <div class="settings-header-actions">
          <button class="console-button" type="button" on:click={saveAccountChanges} disabled={accountSaving || settingsLoading}>
            {accountSaving ? 'Saving...' : 'Save'}
          </button>
          <button class="settings-close-button" type="button" aria-label="Close account" on:click={closeAccountModal}>✕</button>
        </div>
      </div>

      <div class="settings-panel">
        <section class="settings-group">
          <div class="settings-group-head">
            <h3>Profile</h3>
          </div>
          <div class="settings-row settings-row-static">
            <div class="settings-row-copy">
              <div class="settings-row-title">Email</div>
              <div class="settings-row-desc">{currentUser?.email || ''}</div>
            </div>
          </div>
          <div class="settings-row settings-row-tall">
            <div class="settings-row-copy">
              <div class="settings-row-title">Username</div>
              <div class="settings-row-desc">Used for identity and future collaboration features.</div>
            </div>
            <div class="settings-row-control">
              <input class="console-input" type="text" bind:value={accountUsername} placeholder="Username" />
            </div>
          </div>
          <div class="settings-row settings-row-tall">
            <div class="settings-row-copy">
              <div class="settings-row-title">Display name</div>
              <div class="settings-row-desc">Shown in the UI when a fuller name is preferred.</div>
            </div>
            <div class="settings-row-control">
              <input class="console-input" type="text" bind:value={accountDisplayName} placeholder="Display name" />
            </div>
          </div>
          <div class="settings-row settings-row-tall">
            <div class="settings-row-copy">
              <div class="settings-row-title">Sidebar label</div>
              <div class="settings-row-desc">Choose which identity value appears in the account button and related UI labels.</div>
            </div>
            <div class="settings-row-control">
              <select class="console-select" bind:value={appSettings.accountLabelMode}>
                <option value="auto">Auto</option>
                <option value="display_name">Display name</option>
                <option value="username">Username</option>
                <option value="email">Email</option>
              </select>
            </div>
          </div>
        </section>

        <section class="settings-group">
          <div class="settings-group-head">
            <h3>Session</h3>
          </div>
          <div class="settings-row settings-row-static">
            <div class="settings-row-copy">
              <div class="settings-row-title">Role</div>
              <div class="settings-row-desc">{currentUser?.is_superuser ? 'Superuser with admin access' : 'Standard workspace member'}</div>
            </div>
          </div>
          <div class="settings-row settings-row-static">
            <div class="settings-row-copy">
              <div class="settings-row-title">Status</div>
              <div class="settings-row-desc">{currentUser?.is_active === false ? 'Inactive' : 'Active'}</div>
            </div>
          </div>
          <div class="settings-row">
            <div class="settings-row-copy">
              <div class="settings-row-title">Sign out</div>
              <div class="settings-row-desc">End the current session on this device.</div>
            </div>
            <div class="settings-row-control">
              <button class="settings-link-button" type="button" on:click={logout}>Sign out</button>
            </div>
          </div>
        </section>

        {#if accountNotice || accountError}
          <div class="settings-footer">
            {#if accountNotice}
              <div class="console-status success">{accountNotice}</div>
            {/if}
            {#if accountError}
              <div class="console-status error">{accountError}</div>
            {/if}
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}
{/if}
