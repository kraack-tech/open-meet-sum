<script lang="ts">
  import { onMount } from 'svelte';
  import { getAPIBaseURL } from '../lib/config.js';

  type AppUser = {
    id: string;
    email: string;
    username?: string;
    display_name?: string;
    is_superuser?: boolean;
    is_active?: boolean;
  };

  type AdminUser = {
    id: string;
    role: string;
    name: string;
    email: string;
    username?: string;
    display_name?: string;
    is_active?: boolean;
    is_superuser?: boolean;
    created_at?: string;
    last_active?: string;
  };

  type GroupMember = {
    user_id: string;
    role: string;
    email: string;
    username?: string;
    display_name?: string;
    is_active?: boolean;
    is_superuser?: boolean;
    created_at?: string;
    joined_at?: string;
  };

  type AdminGroup = {
    id: string;
    name: string;
    description?: string;
    sharing_scope: string;
    permissions: Record<string, any>;
    user_count: number;
    created_at?: string;
    updated_at?: string;
    members: GroupMember[];
  };

  type Totals = {
    user_count: number;
    chat_count: number;
    meeting_count: number;
    summary_count: number;
    group_count: number;
  };

  type SettingsPayload = {
    general: Record<string, any>;
    connections: Array<Record<string, any>>;
    models: Array<Record<string, any>>;
    model_routing: Record<string, any>;
    audio: Record<string, any>;
    database: Record<string, any>;
  };

  type TopTab = 'users' | 'groups' | 'settings';
  type UsersTab = 'all' | 'admins' | 'active';
  type GroupsTab = 'all' | 'with_members' | 'empty';
  type SettingsTab = 'general' | 'connections' | 'assistant_model' | 'summary_model' | 'models' | 'audio' | 'database';
  type GroupEditorTab = 'general' | 'permissions' | 'users';
  type PermissionTarget = 'users' | 'groups';
  type AdminSpeaker = {
    id: string;
    name: string;
    sample_count: number;
    updated_at?: string;
  };

  export let authToken = '';
  export let currentUser: AppUser | null = null;

  const API_BASE = getAPIBaseURL();

  let loading = false;
  let error = '';
  let notice = '';

  let activeTab: TopTab = 'users';
  let activeUsersTab: UsersTab = 'all';
  let activeGroupsTab: GroupsTab = 'all';
  let activeSettingsTab: SettingsTab = 'general';
  let activeGroupEditorTab: GroupEditorTab = 'general';
  let usersPaneTitle = 'All users';
  let usersPaneDescription = 'All users with role, contact info, last activity, and creation date.';
  let groupsPaneTitle = 'All groups';
  let groupsPaneDescription = 'Manage groups, sharing scope, permissions, and membership.';
  let settingsPaneTitle = 'General';
  let settingsPaneDescription = 'Workspace-wide defaults and policy settings.';

  let users: AdminUser[] = [];
  let groups: AdminGroup[] = [];
  let totals: Totals = {
    user_count: 0,
    chat_count: 0,
    meeting_count: 0,
    summary_count: 0,
    group_count: 0,
  };

  let userDefaults: Record<string, any> = {};
  let groupDefaults: Record<string, any> = {};
  let settings: SettingsPayload = {
    general: {},
    connections: [],
    models: [],
    model_routing: {
      summary_model_id: '',
      assistant_model_id: '',
    },
    audio: {},
    database: {},
  };
  let speakers: AdminSpeaker[] = [];
  let speakerDeletingId = '';

  let showPermissionsModal = false;
  let permissionTarget: PermissionTarget = 'users';
  let permissionDraft: Record<string, any> = {};
  let permissionSaving = false;

  let showGroupModal = false;
  let groupSaving = false;
  let memberSaving = false;
  let showConnectionModal = false;
  let connectionSaving = false;
  let modelDiscoveryInProgress = false;
  let ollamaEnabled = false;
  let openaiEnabled = false;
  let editingConnectionKind: 'ollama' | 'openai' = 'ollama';
  let editingModelId = '';
  let connectionDraft: Record<string, any> = {};
  let editingGroupId = '';
  let selectedGroupUserId = '';
  let selectedGroupUserRole = 'member';
  let groupDraft = createEmptyGroupDraft();

  function createEmptyGroupDraft() {
    return {
      name: '',
      description: '',
      sharing_scope: 'group_admins',
      permissions: {} as Record<string, any>,
    };
  }

  function cloneValue<T>(value: T): T {
    return JSON.parse(JSON.stringify(value));
  }

  async function apiFetch(path: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers || {});
    if (!headers.has('Content-Type') && options.body) {
      headers.set('Content-Type', 'application/json');
    }
    if (authToken) {
      headers.set('Authorization', `Bearer ${authToken}`);
    }

    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const raw = await response.text();
      let message = raw;
      try {
        const payload = JSON.parse(raw || '{}');
        message = payload?.detail || payload?.message || raw;
      } catch {
        message = raw;
      }
      throw new Error(message || `Request failed (${response.status})`);
    }

    return response.json();
  }

  async function loadPanel() {
    if (!authToken || !currentUser?.is_superuser) return;
    loading = true;
    error = '';
    try {
      const payload = await apiFetch('/admin/panel');
      users = payload.users || [];
      groups = payload.groups || [];
      totals = payload.totals || totals;
      userDefaults = payload.user_defaults || {};
      groupDefaults = payload.group_defaults || {};
      settings = payload.settings || settings;
      settings.model_routing = {
        summary_model_id: '',
        assistant_model_id: '',
        ...(settings.model_routing || {}),
      };
      syncConnectionTogglesFromSettings();
      await loadSpeakers();
    } catch (loadError: any) {
      error = loadError?.message || 'Unable to load admin panel.';
    } finally {
      loading = false;
    }
  }

  async function loadSpeakers() {
    try {
      const payload = await apiFetch('/speakers');
      speakers = Array.isArray(payload?.items) ? payload.items : [];
    } catch {
      speakers = [];
    }
  }

  async function removeSpeaker(speaker: AdminSpeaker) {
    if (!speaker?.id) return;
    if (!window.confirm(`Remove speaker \"${speaker.name}\"?`)) return;
    speakerDeletingId = speaker.id;
    error = '';
    notice = '';
    try {
      await apiFetch(`/speakers/${speaker.id}`, {
        method: 'DELETE',
      });
      speakers = speakers.filter((item) => item.id !== speaker.id);
      notice = `Speaker ${speaker.name} removed.`;
    } catch (saveError: any) {
      error = saveError?.message || 'Unable to remove speaker.';
    } finally {
      speakerDeletingId = '';
    }
  }

  async function savePermissionDefaults() {
    permissionSaving = true;
    error = '';
    notice = '';
    try {
      await apiFetch(permissionTarget === 'users' ? '/admin/defaults/users' : '/admin/defaults/groups', {
        method: 'PATCH',
        body: JSON.stringify({ permissions: permissionDraft }),
      });
      if (permissionTarget === 'users') {
        userDefaults = cloneValue(permissionDraft);
      } else {
        groupDefaults = cloneValue(permissionDraft);
      }
      notice = `${permissionTarget === 'users' ? 'User' : 'Group'} defaults updated.`;
      showPermissionsModal = false;
    } catch (saveError: any) {
      error = saveError?.message || 'Unable to save default permissions.';
    } finally {
      permissionSaving = false;
    }
  }

  function openPermissionsModal(target: PermissionTarget) {
    permissionTarget = target;
    permissionDraft = cloneValue(target === 'users' ? userDefaults : groupDefaults);
    showPermissionsModal = true;
  }

  function openCreateGroupModal() {
    editingGroupId = '';
    groupDraft = createEmptyGroupDraft();
    activeGroupEditorTab = 'general';
    selectedGroupUserId = '';
    selectedGroupUserRole = 'member';
    showGroupModal = true;
  }

  function openEditGroupModal(group: AdminGroup) {
    editingGroupId = group.id;
    groupDraft = {
      name: group.name,
      description: group.description || '',
      sharing_scope: group.sharing_scope || 'group_admins',
      permissions: cloneValue(group.permissions || {}),
    };
    activeGroupEditorTab = 'general';
    selectedGroupUserId = '';
    selectedGroupUserRole = 'member';
    showGroupModal = true;
  }

  function getEditingGroup() {
    return groups.find((group) => group.id === editingGroupId) || null;
  }

  async function saveGroup() {
    groupSaving = true;
    error = '';
    notice = '';
    try {
      await apiFetch(editingGroupId ? `/admin/groups/${editingGroupId}` : '/admin/groups', {
        method: editingGroupId ? 'PATCH' : 'POST',
        body: JSON.stringify(groupDraft),
      });
      await loadPanel();
      showGroupModal = false;
      notice = editingGroupId ? 'Group updated.' : 'Group created.';
    } catch (saveError: any) {
      error = saveError?.message || 'Unable to save group.';
    } finally {
      groupSaving = false;
    }
  }

  function getAvailableUsersForGroup() {
    const group = getEditingGroup();
    const existingIds = new Set((group?.members || []).map((member) => member.user_id));
    return users.filter((user) => !existingIds.has(user.id));
  }

  async function addUserToGroup() {
    if (!editingGroupId || !selectedGroupUserId) return;
    memberSaving = true;
    error = '';
    notice = '';
    try {
      await apiFetch(`/admin/groups/${editingGroupId}/members`, {
        method: 'POST',
        body: JSON.stringify({ user_id: selectedGroupUserId, role: selectedGroupUserRole }),
      });
      selectedGroupUserId = '';
      selectedGroupUserRole = 'member';
      await loadPanel();
      notice = 'User added to group.';
    } catch (saveError: any) {
      error = saveError?.message || 'Unable to add user to group.';
    } finally {
      memberSaving = false;
    }
  }

  async function removeUserFromGroup(userId: string) {
    if (!editingGroupId) return;
    memberSaving = true;
    error = '';
    notice = '';
    try {
      await apiFetch(`/admin/groups/${editingGroupId}/members/${userId}`, {
        method: 'DELETE',
      });
      await loadPanel();
      notice = 'User removed from group.';
    } catch (saveError: any) {
      error = saveError?.message || 'Unable to remove user from group.';
    } finally {
      memberSaving = false;
    }
  }

  async function saveSettingsSection(section: SettingsTab) {
    error = '';
    notice = '';
    try {
      await apiFetch(`/admin/settings/${section}`, {
        method: 'PATCH',
        body: JSON.stringify({ value: settings[section] }),
      });
      notice = `${capitalize(section)} settings updated.`;
    } catch (saveError: any) {
      error = saveError?.message || 'Unable to save settings section.';
    }
  }

  async function saveModelRouting() {
    error = '';
    notice = '';
    try {
      await apiFetch('/admin/settings/model_routing', {
        method: 'PATCH',
        body: JSON.stringify({ value: settings.model_routing }),
      });
      notice = 'Model routing updated.';
    } catch (saveError: any) {
      error = saveError?.message || 'Unable to save model routing.';
    }
  }

  function getOllamaConnection() {
    return settings.connections.find((connection) => (connection.provider || '').toLowerCase() === 'ollama') || null;
  }

  function getOpenAIConnection() {
    return (
      settings.connections.find((connection) => {
        const provider = (connection.provider || '').toLowerCase();
        return provider === 'openai-compatible' || provider === 'openai' || provider === 'azure-openai';
      }) || null
    );
  }

  function ensureConnection(kind: 'ollama' | 'openai') {
    const existing = kind === 'ollama' ? getOllamaConnection() : getOpenAIConnection();
    if (existing) return existing;

    const created =
      kind === 'ollama'
        ? {
            id: `connection-ollama-${Date.now()}`,
            name: 'Ollama',
            provider: 'ollama',
            base_url: 'http://localhost:11434',
            enabled: false,
            local_model: '',
          }
        : {
            id: `connection-openai-${Date.now()}`,
            name: 'OpenAI API',
            provider: 'openai-compatible',
            connection_type: 'azure',
            base_url: '',
            auth_type: 'bearer',
            api_key: '',
            api_version: '',
            model_ids: [],
            enabled: false,
          };

    settings.connections = [...settings.connections, created];
    return created;
  }

  function getConnectionUrl(kind: 'ollama' | 'openai') {
    const connection = kind === 'ollama' ? getOllamaConnection() : getOpenAIConnection();
    if (!connection) return 'Not configured';
    return connection.base_url || 'Not configured';
  }

  function isOllamaProvider(provider?: string) {
    return (provider || '').toLowerCase() === 'ollama';
  }

  function isOpenAIProvider(provider?: string) {
    const normalized = (provider || '').toLowerCase();
    return normalized === 'openai-compatible' || normalized === 'openai' || normalized === 'azure-openai';
  }

  function syncConnectionTogglesFromSettings() {
    const nextOllama = settings.connections.some((connection) => isOllamaProvider(connection.provider) && Boolean(connection.enabled));
    const nextOpenai = settings.connections.some((connection) => isOpenAIProvider(connection.provider) && Boolean(connection.enabled));

    // Keep toggle state mutually exclusive if backend data has both enabled.
    if (nextOllama && nextOpenai) {
      ollamaEnabled = true;
      openaiEnabled = false;
      settings.connections = settings.connections.map((connection) => {
        if (isOpenAIProvider(connection.provider)) return { ...connection, enabled: false };
        return connection;
      });
      return;
    }

    ollamaEnabled = nextOllama;
    openaiEnabled = nextOpenai;
  }

  function applyConnectionToggleState() {
    ensureConnection('ollama');
    ensureConnection('openai');

    settings.connections = settings.connections.map((connection) => {
      if (isOllamaProvider(connection.provider)) {
        return { ...connection, enabled: ollamaEnabled };
      }
      if (isOpenAIProvider(connection.provider)) {
        return { ...connection, enabled: openaiEnabled };
      }
      return connection;
    });
  }

  function onToggleOllama() {
    if (ollamaEnabled) {
      openaiEnabled = false;
    }
    applyConnectionToggleState();
  }

  function onToggleOpenAI() {
    if (openaiEnabled) {
      ollamaEnabled = false;
    }
    applyConnectionToggleState();
  }

  function openConnectionSettings(kind: 'ollama' | 'openai') {
    editingConnectionKind = kind;
    const connection = ensureConnection(kind);
    connectionDraft = cloneValue(connection);
    if (kind === 'openai') {
      connectionDraft.provider = 'openai-compatible';
      connectionDraft.connection_type = connectionDraft.connection_type || 'azure';
      connectionDraft.auth_type = connectionDraft.auth_type || 'bearer';
      connectionDraft.api_key = connectionDraft.api_key || '';
      if (Array.isArray(connectionDraft.model_ids)) {
        connectionDraft.model_ids_text = connectionDraft.model_ids.join(', ');
      } else {
        connectionDraft.model_ids_text = String(connectionDraft.model_ids || '').trim();
      }
    }
    showConnectionModal = true;
  }

  function closeConnectionModal() {
    showConnectionModal = false;
  }

  function saveConnectionSettings() {
    connectionSaving = true;
    try {
      const list = [...settings.connections];
      const providerKind = editingConnectionKind === 'ollama' ? 'ollama' : 'openai-compatible';
      const index = list.findIndex((item) => {
        const provider = (item.provider || '').toLowerCase();
        if (editingConnectionKind === 'ollama') return provider === 'ollama';
        return provider === 'openai-compatible' || provider === 'openai' || provider === 'azure-openai';
      });

      const next = cloneValue(connectionDraft);
      if (editingConnectionKind === 'ollama') {
        next.provider = 'ollama';
      } else {
        next.provider = providerKind;
        next.connection_type = String(connectionDraft.connection_type || 'azure');
        next.auth_type = String(connectionDraft.auth_type || 'bearer');
        next.api_key = String(connectionDraft.api_key || '').trim();
        next.model_ids = String(connectionDraft.model_ids_text || '')
          .split(',')
          .map((value: string) => value.trim())
          .filter(Boolean);
        delete next.model_ids_text;
      }

      if (index >= 0) {
        list[index] = { ...list[index], ...next };
      } else {
        list.push(next);
      }

      settings.connections = list;
      showConnectionModal = false;
      notice = `${editingConnectionKind === 'ollama' ? 'Ollama' : 'OpenAI API'} connection updated.`;
      error = '';
    } catch (saveError: any) {
      error = saveError?.message || 'Unable to save connection settings.';
    } finally {
      connectionSaving = false;
    }
  }

  function openModelEditor(modelId: string) {
    editingModelId = modelId;
  }

  function closeModelEditor() {
    editingModelId = '';
  }

  async function discoverConnectedModels() {
    modelDiscoveryInProgress = true;
    error = '';
    notice = '';
    try {
      const payload = await apiFetch('/admin/connections/discover-models', {
        method: 'POST',
      });
      settings.models = Array.isArray(payload.models) ? payload.models : [];
      const attempted = Number(payload.attempted_connections || 0);
      const ok = Number(payload.successful_connections || 0);
      const failed = Number(payload.failed_connections || 0);
      notice = `Discovered ${settings.models.length} model(s) from ${ok}/${attempted} attempted connection(s)${failed ? `, ${failed} failed` : ''}.`;
    } catch (discoverError: any) {
      error = discoverError?.message || 'Unable to discover models from connections.';
    } finally {
      modelDiscoveryInProgress = false;
    }
  }

  async function saveConnectionsAndDiscoverModels() {
    await saveSettingsSection('connections');
    if (error) return;
    await discoverConnectedModels();
  }

  function getConnectionName(model: Record<string, any>) {
    const connectionId = String(model.connection_id || '').trim();
    if (!connectionId) return 'Unknown connection';
    const connection = settings.connections.find((item) => String(item.id || '').trim() === connectionId);
    return String(connection?.name || connectionId);
  }

  async function downloadExport(resource: string) {
    error = '';
    notice = '';
    try {
      const payload = await apiFetch(`/admin/export/${resource}`);
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `admin-${resource}-export.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      notice = `${capitalize(resource)} export downloaded.`;
    } catch (downloadError: any) {
      error = downloadError?.message || 'Unable to export data.';
    }
  }

  function formatDate(value?: string) {
    if (!value) return 'Not available';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleString();
  }

  function capitalize(value: string) {
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function getVisibleUsers() {
    if (activeUsersTab === 'admins') {
      return users.filter((user) => user.is_superuser || user.role === 'admin');
    }
    if (activeUsersTab === 'active') {
      return users.filter((user) => user.is_active !== false);
    }
    return users;
  }

  function syncUsersPane() {
    if (activeUsersTab === 'admins') {
      usersPaneTitle = 'Admins';
      usersPaneDescription = 'Users with admin privileges.';
      return;
    }
    if (activeUsersTab === 'active') {
      usersPaneTitle = 'Active users';
      usersPaneDescription = 'Users currently marked active.';
      return;
    }
    usersPaneTitle = 'All users';
    usersPaneDescription = 'All users with role, contact info, last activity, and creation date.';
  }

  function syncGroupsPane() {
    if (activeGroupsTab === 'with_members') {
      groupsPaneTitle = 'Groups with members';
      groupsPaneDescription = 'Groups that currently have members.';
      return;
    }
    if (activeGroupsTab === 'empty') {
      groupsPaneTitle = 'Empty groups';
      groupsPaneDescription = 'Groups without members yet.';
      return;
    }
    groupsPaneTitle = 'All groups';
    groupsPaneDescription = 'Manage groups, sharing scope, permissions, and membership.';
  }

  function syncSettingsPane() {
    if (activeSettingsTab === 'general') {
      settingsPaneTitle = 'General';
      settingsPaneDescription = 'Workspace-wide defaults and policy settings.';
      return;
    }
    if (activeSettingsTab === 'connections') {
      settingsPaneTitle = 'Connections';
      settingsPaneDescription = 'Configure model backends and provider endpoints.';
      return;
    }
    if (activeSettingsTab === 'assistant_model') {
      settingsPaneTitle = 'Assistant';
      settingsPaneDescription = 'Model used for agent chat and summary feedback (HITL).';
      return;
    }
    if (activeSettingsTab === 'summary_model') {
      settingsPaneTitle = 'Summary';
      settingsPaneDescription = 'Select which model from Models is used for summary generation (or default FLAN).';
      return;
    }
    if (activeSettingsTab === 'models') {
      settingsPaneTitle = 'Models';
      settingsPaneDescription = 'Connected model runtimes discovered from provider connections; edit prompt and capabilities only.';
      return;
    }
    if (activeSettingsTab === 'audio') {
      settingsPaneTitle = 'Audio';
      settingsPaneDescription = 'Set transcription and language defaults.';
      return;
    }
    settingsPaneTitle = 'Database';
    settingsPaneDescription = 'Export workspace datasets.';
  }

  function selectTopTab(tab: TopTab) {
    activeTab = tab;
    if (tab === 'users') {
      syncUsersPane();
      return;
    }
    if (tab === 'groups') {
      syncGroupsPane();
      return;
    }
    syncSettingsPane();
  }

  function selectUsersTab(tab: UsersTab) {
    activeUsersTab = tab;
    syncUsersPane();
  }

  function selectGroupsTab(tab: GroupsTab) {
    activeGroupsTab = tab;
    syncGroupsPane();
  }

  function selectSettingsTab(tab: SettingsTab) {
    activeSettingsTab = tab;
    syncSettingsPane();
  }

  function getVisibleGroups() {
    if (activeGroupsTab === 'with_members') {
      return groups.filter((group) => group.user_count > 0);
    }
    if (activeGroupsTab === 'empty') {
      return groups.filter((group) => group.user_count === 0);
    }
    return groups;
  }

  function updatePermission(key: string, value: any) {
    permissionDraft = {
      ...permissionDraft,
      [key]: value,
    };
  }

  function updateGroupPermission(key: string, value: any) {
    groupDraft = {
      ...groupDraft,
      permissions: {
        ...groupDraft.permissions,
        [key]: value,
      },
    };
  }

  function getPermissionEntries(source: Record<string, any>) {
    return Object.entries(source || {});
  }

  function getGroupPermissionEntries() {
    return Object.entries({ ...groupDefaults, ...groupDraft.permissions });
  }

  function closePermissionsModal() {
    showPermissionsModal = false;
  }

  function closeGroupModal() {
    showGroupModal = false;
  }

  onMount(async () => {
    await loadPanel();
    selectTopTab(activeTab);
  });
</script>

<svelte:window
  on:keydown={(event) => {
    if (event.key === 'Escape') {
      if (showPermissionsModal) closePermissionsModal();
      if (showGroupModal) closeGroupModal();
      if (showConnectionModal) closeConnectionModal();
    }
  }}
/>

<div class="admin-shell">
  {#if !currentUser?.is_superuser}
    <section class="admin-card admin-card-wide">
      <h3>Admin access required</h3>
      <p class="admin-copy">This page is only available to admins.</p>
    </section>
  {:else if loading}
    <section class="admin-card admin-card-wide">
      <div class="admin-empty">Loading admin data...</div>
    </section>
  {:else}
    <section class="admin-workspace">
      <div class="admin-tab-row">
        <button class:active={activeTab === 'users'} type="button" on:click={() => selectTopTab('users')}>Users</button>
        <button class:active={activeTab === 'groups'} type="button" on:click={() => selectTopTab('groups')}>Groups</button>
        <button class:active={activeTab === 'settings'} type="button" on:click={() => selectTopTab('settings')}>Settings</button>
      </div>

      <div class="admin-tab-body">
        {#if activeTab === 'users'}
          <section class="admin-card admin-card-wide tab-layout tab-section">
            <aside class="tab-sidebar">
              <div class="sidebar-nav">
                <button class:active={activeUsersTab === 'all'} type="button" on:click={() => selectUsersTab('all')}>
                  <span>All users</span>
                  <strong>{users.length}</strong>
                </button>
                <button class:active={activeUsersTab === 'admins'} type="button" on:click={() => selectUsersTab('admins')}>
                  <span>Admins</span>
                  <strong>{users.filter((user) => user.is_superuser || user.role === 'admin').length}</strong>
                </button>
                <button class:active={activeUsersTab === 'active'} type="button" on:click={() => selectUsersTab('active')}>
                  <span>Active</span>
                  <strong>{users.filter((user) => user.is_active !== false).length}</strong>
                </button>
              </div>

              <button class="admin-secondary" type="button" on:click={() => openPermissionsModal('users')}>Default permissions</button>

              <section class="admin-stats sidebar-stats">
                <div class="admin-stat"><span>Users</span><strong>{totals.user_count}</strong></div>
                <div class="admin-stat"><span>Groups</span><strong>{totals.group_count}</strong></div>
                <div class="admin-stat"><span>Chats</span><strong>{totals.chat_count}</strong></div>
                <div class="admin-stat"><span>Meetings</span><strong>{totals.meeting_count}</strong></div>
                <div class="admin-stat"><span>Summaries</span><strong>{totals.summary_count}</strong></div>
              </section>

              {#if notice}
                <div class="admin-notice success">{notice}</div>
              {/if}
              {#if error}
                <div class="admin-notice error">{error}</div>
              {/if}
            </aside>

            <div class="tab-main">
              <div class="admin-card-head">
                <div>
                  <h3>{usersPaneTitle}</h3>
                  <p class="admin-copy">{usersPaneDescription}</p>
                </div>
              </div>
              <div class="section-title-divider" aria-hidden="true"></div>

              <div class="admin-table">
                <div class="admin-table-head admin-table-row">
                  <span>Role</span>
                  <span>Name</span>
                  <span>Email</span>
                  <span>Last active</span>
                  <span>Created</span>
                </div>
                {#if getVisibleUsers().length}
                  {#each getVisibleUsers() as user}
                    <div class="admin-table-row">
                      <span><span class="admin-pill">{user.role}</span></span>
                      <span>{user.name}</span>
                      <span>{user.email}</span>
                      <span>{formatDate(user.last_active)}</span>
                      <span>{formatDate(user.created_at)}</span>
                    </div>
                  {/each}
                {:else}
                  <div class="admin-empty">No users found.</div>
                {/if}
              </div>
            </div>
          </section>
        {/if}

        {#if activeTab === 'groups'}
          <section class="admin-card admin-card-wide tab-layout tab-section">
            <aside class="tab-sidebar">
              <div class="sidebar-nav">
                <button class:active={activeGroupsTab === 'all'} type="button" on:click={() => selectGroupsTab('all')}>
                  <span>All groups</span>
                  <strong>{groups.length}</strong>
                </button>
                <button class:active={activeGroupsTab === 'with_members'} type="button" on:click={() => selectGroupsTab('with_members')}>
                  <span>With members</span>
                  <strong>{groups.filter((group) => group.user_count > 0).length}</strong>
                </button>
                <button class:active={activeGroupsTab === 'empty'} type="button" on:click={() => selectGroupsTab('empty')}>
                  <span>Empty</span>
                  <strong>{groups.filter((group) => group.user_count === 0).length}</strong>
                </button>
              </div>

              <button class="admin-secondary" type="button" on:click={() => openPermissionsModal('groups')}>Default permissions</button>
              <button class="admin-primary" type="button" on:click={openCreateGroupModal}>New group</button>

              {#if notice}
                <div class="admin-notice success">{notice}</div>
              {/if}
              {#if error}
                <div class="admin-notice error">{error}</div>
              {/if}
            </aside>

            <div class="tab-main">
              <div class="admin-card-head">
                <div>
                  <h3>{groupsPaneTitle}</h3>
                  <p class="admin-copy">{groupsPaneDescription}</p>
                </div>
              </div>
              <div class="section-title-divider" aria-hidden="true"></div>

              <div class="group-list">
                {#if getVisibleGroups().length}
                  {#each getVisibleGroups() as group}
                    <div class="group-card">
                      <div class="group-card-main">
                        <div class="group-card-title-row">
                          <h4>{group.name}</h4>
                          <span class="admin-pill">{group.user_count} users</span>
                        </div>
                        <p>{group.description || 'No group description yet.'}</p>
                        <div class="group-card-meta">Sharing: {group.sharing_scope}</div>
                      </div>
                      <button class="admin-icon-button" type="button" aria-label="Edit group" on:click={() => openEditGroupModal(group)}>✎</button>
                    </div>
                  {/each}
                {:else}
                  <div class="admin-empty">No groups for this filter.</div>
                {/if}
              </div>
            </div>
          </section>
        {/if}

        {#if activeTab === 'settings'}
          <section class="admin-card admin-card-wide tab-layout tab-section">
            <aside class="tab-sidebar">
              <div class="sidebar-nav">
                <button class:active={activeSettingsTab === 'general'} type="button" on:click={() => selectSettingsTab('general')}>
                  <span>General</span>
                </button>
                <button class:active={activeSettingsTab === 'connections'} type="button" on:click={() => selectSettingsTab('connections')}>
                  <span>Connections</span>
                </button>
                <button class:active={activeSettingsTab === 'models'} type="button" on:click={() => selectSettingsTab('models')}>
                  <span>Models</span>
                </button>
                <button class:active={activeSettingsTab === 'assistant_model'} type="button" on:click={() => selectSettingsTab('assistant_model')}>
                  <span>Assistant</span>
                </button>
                <button class:active={activeSettingsTab === 'summary_model'} type="button" on:click={() => selectSettingsTab('summary_model')}>
                  <span>Summary</span>
                </button>
                <button class:active={activeSettingsTab === 'audio'} type="button" on:click={() => selectSettingsTab('audio')}>
                  <span>Audio</span>
                </button>
                <button class:active={activeSettingsTab === 'database'} type="button" on:click={() => selectSettingsTab('database')}>
                  <span>Database</span>
                </button>
              </div>

              {#if notice}
                <div class="admin-notice success">{notice}</div>
              {/if}
              {#if error}
                <div class="admin-notice error">{error}</div>
              {/if}
            </aside>

            <div class="tab-main">
              <div class="admin-card-head">
                <div>
                  <h3>{settingsPaneTitle}</h3>
                  <p class="admin-copy">{settingsPaneDescription}</p>
                </div>
              </div>
              <div class="section-title-divider" aria-hidden="true"></div>

            {#if activeSettingsTab === 'general'}
              <div class="settings-form-grid">
                <label>
                  <span>Workspace name</span>
                  <input bind:value={settings.general.workspace_name} />
                </label>
                <label>
                  <span>Default user role</span>
                  <select bind:value={settings.general.default_user_role}>
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                  </select>
                </label>
                <label class="wide">
                  <span>Audit retention days</span>
                  <input type="number" bind:value={settings.general.audit_retention_days} />
                </label>
                <label class="checkbox-row wide">
                  <input type="checkbox" bind:checked={settings.general.allow_self_signup} />
                  <span>Allow self signup</span>
                </label>
              </div>
              <div class="section-actions">
                <button class="admin-primary" type="button" on:click={() => saveSettingsSection('general')}>Save general</button>
              </div>
            {/if}

            {#if activeSettingsTab === 'connections'}
              <div class="connection-list">
                <div class="connection-row">
                  <div class="connection-main">
                    <strong>Ollama</strong>
                    <span>{getConnectionUrl('ollama')}</span>
                  </div>
                  <div class="connection-actions">
                    <button class="admin-icon-button" type="button" aria-label="Configure Ollama" on:click={() => openConnectionSettings('ollama')}>⚙</button>
                    <label class="switch" aria-label="Enable Ollama">
                      <input type="checkbox" bind:checked={ollamaEnabled} on:change={onToggleOllama} />
                      <span class="slider"></span>
                    </label>
                  </div>
                </div>

                <div class="connection-row">
                  <div class="connection-main">
                    <strong>OpenAI API</strong>
                    <span>{getConnectionUrl('openai')}</span>
                  </div>
                  <div class="connection-actions">
                    <button class="admin-icon-button" type="button" aria-label="Configure OpenAI API" on:click={() => openConnectionSettings('openai')}>⚙</button>
                    <label class="switch" aria-label="Enable OpenAI API">
                      <input type="checkbox" bind:checked={openaiEnabled} on:change={onToggleOpenAI} />
                      <span class="slider"></span>
                    </label>
                  </div>
                </div>
              </div>
              <div class="section-actions">
                <button class="admin-primary" type="button" disabled={modelDiscoveryInProgress} on:click={saveConnectionsAndDiscoverModels}>
                  {modelDiscoveryInProgress ? 'Saving and discovering...' : 'Save connections'}
                </button>
              </div>
            {/if}

            {#if activeSettingsTab === 'assistant_model'}
              <div class="stack-card">
                <div class="stack-card-head">
                  <strong>Assistant</strong>
                </div>
                <div class="settings-form-grid">
                  <label>
                    <span>Assistant model (chat + feedback)</span>
                    <select bind:value={settings.model_routing.assistant_model_id}>
                      <option value="">Auto</option>
                      {#each settings.models as model}
                        <option value={model.id}>{model.name || model.id || model.runtime || 'Unnamed model'}</option>
                      {/each}
                    </select>
                  </label>
                </div>
                <div class="section-actions">
                  <button class="admin-primary" type="button" on:click={saveModelRouting}>Save assistant</button>
                </div>
              </div>
            {/if}

            {#if activeSettingsTab === 'summary_model'}
              <div class="stack-card">
                <div class="stack-card-head">
                  <strong>Summary</strong>
                </div>
                <div class="settings-form-grid">
                  <label>
                    <span>Summary model</span>
                    <select bind:value={settings.model_routing.summary_model_id}>
                      <option value="">Default (FLAN-T5)</option>
                      {#each settings.models as model}
                        <option value={model.id}>{model.name || model.id || model.runtime || 'Unnamed model'}</option>
                      {/each}
                    </select>
                  </label>
                </div>
                <div class="section-actions">
                  <button class="admin-primary" type="button" on:click={saveModelRouting}>Save summary</button>
                </div>
              </div>
            {/if}

            {#if activeSettingsTab === 'models'}
              <div class="stack-list">
                {#each settings.models as model}
                  <div class="stack-card">
                    <div class="stack-card-head">
                      <strong>{model.name || model.runtime || model.id || 'Unnamed model'}</strong>
                      <button class="admin-icon-button" type="button" aria-label="Edit model" on:click={() => openModelEditor(String(model.id || ''))}>✎</button>
                    </div>
                    <div class="model-meta">
                      <span>Provider: {model.provider || 'unknown'}</span>
                      <span>Runtime: {model.runtime || 'unknown'}</span>
                      <span>Connection: {getConnectionName(model)}</span>
                    </div>

                    {#if editingModelId === String(model.id || '')}
                      <div class="settings-form-grid">
                        <label>
                          <span>Name</span>
                          <input bind:value={model.name} />
                        </label>
                        <label>
                          <span>Knowledge scope</span>
                          <select bind:value={model.knowledge_scope}>
                            <option value="workspace">Workspace</option>
                            <option value="group">Group</option>
                            <option value="none">None</option>
                          </select>
                        </label>
                        <label class="wide">
                          <span>Capabilities (comma-separated)</span>
                          <input
                            value={(model.capabilities || []).join(', ')}
                            on:input={(event) => {
                              model.capabilities = (event.currentTarget as HTMLInputElement).value
                                .split(',')
                                .map((item) => item.trim())
                                .filter(Boolean);
                            }}
                          />
                        </label>
                        <label class="wide">
                          <span>System prompt</span>
                          <textarea bind:value={model.system_prompt} rows="4"></textarea>
                        </label>
                      </div>
                      <div class="section-actions">
                        <button class="admin-secondary" type="button" on:click={closeModelEditor}>Done</button>
                      </div>
                    {/if}
                  </div>
                {/each}

                {#if !settings.models.length}
                  <div class="admin-empty">No connected models found. Save connections first.</div>
                {/if}
              </div>
              <div class="section-actions">
                <button class="admin-secondary" type="button" disabled={modelDiscoveryInProgress} on:click={discoverConnectedModels}>
                  {modelDiscoveryInProgress ? 'Refreshing...' : 'Refresh connected models'}
                </button>
                <button class="admin-primary" type="button" on:click={() => saveSettingsSection('models')}>Save models</button>
              </div>
            {/if}

            {#if activeSettingsTab === 'audio'}
              <div class="settings-form-grid">
                <label>
                  <span>Transcription backend</span>
                  <select bind:value={settings.audio.transcription_backend}>
                    <option value="local_whisper">Local Whisper</option>
                    <option value="api">API model</option>
                  </select>
                </label>
                <label>
                  <span>API provider</span>
                  <select bind:value={settings.audio.api_provider}>
                    <option value="openai-compatible">OpenAI-compatible API</option>
                    <option value="llama-api">Llama API</option>
                  </select>
                </label>
                <label>
                  <span>Local Whisper model</span>
                  <input bind:value={settings.audio.local_model} />
                </label>
                <label>
                  <span>Default language</span>
                  <input bind:value={settings.audio.default_language} />
                </label>
              </div>
              <div class="section-actions">
                <button class="admin-primary" type="button" on:click={() => saveSettingsSection('audio')}>Save audio</button>
              </div>
            {/if}

            {#if activeSettingsTab === 'database'}
              <div class="database-grid">
                <div class="database-card">
                  <strong>Users</strong>
                  <span>{totals.user_count} records</span>
                  <button class="admin-secondary" type="button" on:click={() => downloadExport('users')}>Export users</button>
                </div>
                <div class="database-card">
                  <strong>Chats</strong>
                  <span>{totals.chat_count} records</span>
                  <button class="admin-secondary" type="button" on:click={() => downloadExport('chats')}>Export chats</button>
                </div>
                <div class="database-card">
                  <strong>Meetings</strong>
                  <span>{totals.meeting_count} records</span>
                  <button class="admin-secondary" type="button" on:click={() => downloadExport('meetings')}>Export meetings</button>
                </div>
                <div class="database-card">
                  <strong>Summaries</strong>
                  <span>{totals.summary_count} records</span>
                  <button class="admin-secondary" type="button" on:click={() => downloadExport('summaries')}>Export summaries</button>
                </div>
                <div class="database-card">
                  <strong>Groups</strong>
                  <span>{totals.group_count} records</span>
                  <button class="admin-secondary" type="button" on:click={() => downloadExport('groups')}>Export groups</button>
                </div>
              </div>

              <div class="stack-card speaker-card">
                <div class="stack-card-head">
                  <strong>Speaker Profiles</strong>
                  <button class="admin-secondary" type="button" on:click={loadSpeakers}>Refresh</button>
                </div>
                {#if speakers.length}
                  <div class="speaker-list">
                    {#each speakers as speaker}
                      <div class="speaker-row">
                        <div class="speaker-main">
                          <strong>{speaker.name}</strong>
                          <span>{speaker.sample_count} sample{speaker.sample_count === 1 ? '' : 's'} • Updated {formatDate(speaker.updated_at)}</span>
                        </div>
                        <button
                          class="admin-text-button"
                          type="button"
                          disabled={speakerDeletingId === speaker.id}
                          on:click={() => removeSpeaker(speaker)}
                        >
                          {speakerDeletingId === speaker.id ? 'Removing...' : 'Remove'}
                        </button>
                      </div>
                    {/each}
                  </div>
                {:else}
                  <div class="admin-empty">No enrolled speakers yet.</div>
                {/if}
              </div>
            {/if}
            </div>
          </section>
        {/if}
      </div>
    </section>
  {/if}
</div>

{#if showPermissionsModal}
  <div
    class="modal-backdrop"
    role="presentation"
    on:click={(event) => {
      if (event.target === event.currentTarget) closePermissionsModal();
    }}
  >
    <div class="modal-shell" role="dialog" aria-modal="true" tabindex="-1">
      <div class="modal-head">
        <div>
          <h3>{permissionTarget === 'users' ? 'Default user permissions' : 'Default group permissions'}</h3>
          <p>Apply baseline permissions for all {permissionTarget}.</p>
        </div>
        <button class="admin-icon-button" type="button" on:click={closePermissionsModal}>×</button>
      </div>
      <div class="permission-list">
        {#each getPermissionEntries(permissionDraft) as [key, value]}
          <div class="permission-row">
            <div>
              <strong>{key.replaceAll('_', ' ')}</strong>
            </div>
            {#if typeof value === 'boolean'}
              <label class="checkbox-row compact">
                <input type="checkbox" checked={value} on:change={(event) => updatePermission(key, (event.currentTarget as HTMLInputElement).checked)} />
                <span>{value ? 'Enabled' : 'Disabled'}</span>
              </label>
            {:else if key === 'visibility'}
              <select bind:value={permissionDraft[key]}>
                <option value="private">Private</option>
                <option value="internal">Internal</option>
                <option value="public">Public</option>
              </select>
            {:else}
              <input value={String(value)} on:input={(event) => updatePermission(key, (event.currentTarget as HTMLInputElement).value)} />
            {/if}
          </div>
        {/each}
      </div>
      <div class="section-actions">
        <button class="admin-secondary" type="button" on:click={closePermissionsModal}>Cancel</button>
        <button class="admin-primary" type="button" disabled={permissionSaving} on:click={savePermissionDefaults}>{permissionSaving ? 'Saving...' : 'Save defaults'}</button>
      </div>
    </div>
  </div>
{/if}

{#if showGroupModal}
  <div
    class="modal-backdrop"
    role="presentation"
    on:click={(event) => {
      if (event.target === event.currentTarget) closeGroupModal();
    }}
  >
    <div class="modal-shell group-modal" role="dialog" aria-modal="true" tabindex="-1">
      <div class="modal-head">
        <div>
          <h3>{editingGroupId ? 'Edit group' : 'Create group'}</h3>
          <p>Configure general details, permissions, and members.</p>
        </div>
        <button class="admin-icon-button" type="button" on:click={closeGroupModal}>×</button>
      </div>

      <div class="admin-subtab-row">
        <button class:active={activeGroupEditorTab === 'general'} type="button" on:click={() => (activeGroupEditorTab = 'general')}>General</button>
        <button class:active={activeGroupEditorTab === 'permissions'} type="button" on:click={() => (activeGroupEditorTab = 'permissions')}>Permissions</button>
        <button class:active={activeGroupEditorTab === 'users'} type="button" on:click={() => (activeGroupEditorTab = 'users')}>Users</button>
      </div>

      {#if activeGroupEditorTab === 'general'}
        <div class="settings-form-grid">
          <label>
            <span>Name</span>
            <input bind:value={groupDraft.name} />
          </label>
          <label>
            <span>Who can share this group</span>
            <select bind:value={groupDraft.sharing_scope}>
              <option value="group_admins">Group admins only</option>
              <option value="all_members">All members</option>
              <option value="admins_only">Platform admins only</option>
            </select>
          </label>
          <label class="wide">
            <span>Group description</span>
            <textarea bind:value={groupDraft.description} rows="4"></textarea>
          </label>
        </div>
      {/if}

      {#if activeGroupEditorTab === 'permissions'}
        <div class="permission-list">
          {#each getGroupPermissionEntries() as [key, value]}
            <div class="permission-row">
              <div>
                <strong>{key.replaceAll('_', ' ')}</strong>
              </div>
              {#if typeof value === 'boolean'}
                <label class="checkbox-row compact">
                  <input type="checkbox" checked={value} on:change={(event) => updateGroupPermission(key, (event.currentTarget as HTMLInputElement).checked)} />
                  <span>{value ? 'Enabled' : 'Disabled'}</span>
                </label>
              {:else if key === 'visibility'}
                <select bind:value={groupDraft.permissions[key]}>
                  <option value="private">Private</option>
                  <option value="internal">Internal</option>
                  <option value="public">Public</option>
                </select>
              {:else}
                <input value={String(value)} on:input={(event) => updateGroupPermission(key, (event.currentTarget as HTMLInputElement).value)} />
              {/if}
            </div>
          {/each}
        </div>
      {/if}

      {#if activeGroupEditorTab === 'users'}
        {#if editingGroupId}
          <div class="member-toolbar">
            <select bind:value={selectedGroupUserId}>
              <option value="">Select user to add</option>
              {#each getAvailableUsersForGroup() as user}
                <option value={user.id}>{user.name} ({user.email})</option>
              {/each}
            </select>
            <select bind:value={selectedGroupUserRole}>
              <option value="member">Member</option>
              <option value="manager">Manager</option>
              <option value="owner">Owner</option>
            </select>
            <button class="admin-primary" type="button" disabled={!selectedGroupUserId || memberSaving} on:click={addUserToGroup}>{memberSaving ? 'Saving...' : 'Add user'}</button>
          </div>

          <div class="member-list">
            {#if getEditingGroup()?.members?.length}
              {#each getEditingGroup()?.members || [] as member}
                <div class="member-row">
                  <div>
                    <strong>{member.display_name || member.username || member.email}</strong>
                    <div>{member.email}</div>
                  </div>
                  <div class="member-actions">
                    <span class="admin-pill">{member.role}</span>
                    <button class="admin-text-button" type="button" disabled={memberSaving} on:click={() => removeUserFromGroup(member.user_id)}>Remove</button>
                  </div>
                </div>
              {/each}
            {:else}
              <div class="admin-empty">No members yet.</div>
            {/if}
          </div>
        {:else}
          <div class="admin-empty">Create the group first, then add users.</div>
        {/if}
      {/if}

      <div class="section-actions">
        <button class="admin-secondary" type="button" on:click={closeGroupModal}>Cancel</button>
        <button class="admin-primary" type="button" disabled={groupSaving} on:click={saveGroup}>{groupSaving ? 'Saving...' : editingGroupId ? 'Save group' : 'Create group'}</button>
      </div>
    </div>
  </div>
{/if}

{#if showConnectionModal}
  <div
    class="modal-backdrop"
    role="presentation"
    on:click={(event) => {
      if (event.target === event.currentTarget) closeConnectionModal();
    }}
  >
    <div class="modal-shell" role="dialog" aria-modal="true" tabindex="-1">
      <div class="modal-head">
        <div>
          <h3>{editingConnectionKind === 'ollama' ? 'Ollama settings' : 'OpenAI API settings'}</h3>
          <p>Configure {editingConnectionKind === 'ollama' ? 'local Ollama' : 'external OpenAI-compatible'} connection fields.</p>
        </div>
        <button class="admin-icon-button" type="button" on:click={closeConnectionModal}>×</button>
      </div>

      {#if editingConnectionKind === 'ollama'}
        <div class="settings-form-grid">
          <label>
            <span>Base URL</span>
            <input bind:value={connectionDraft.base_url} placeholder="http://localhost:11434" />
          </label>
          <label>
            <span>Local model</span>
            <input bind:value={connectionDraft.local_model} placeholder="llama3.2:latest" />
          </label>
        </div>
      {:else}
        <div class="settings-form-grid">
          <label>
            <span>Connection type</span>
            <select bind:value={connectionDraft.connection_type}>
              <option value="azure">Azure OpenAI</option>
              <option value="aifoundry">AI Foundry</option>
            </select>
          </label>
          <label>
            <span>Auth mode</span>
            <select bind:value={connectionDraft.auth_type}>
              <option value="bearer">Bearer token</option>
              <option value="api-key">API key header</option>
            </select>
          </label>
          <label>
            <span>{connectionDraft.auth_type === 'api-key' ? 'API key' : 'Bearer'}</span>
            <input
              type="password"
              bind:value={connectionDraft.api_key}
              placeholder={connectionDraft.auth_type === 'api-key' ? 'Paste API key' : 'Paste bearer token'}
            />
          </label>
          <label class="wide">
            <span>URL</span>
            <input bind:value={connectionDraft.base_url} placeholder="https://your-endpoint/" />
          </label>
          <label>
            <span>API version</span>
            <input bind:value={connectionDraft.api_version} placeholder="2024-02-15-preview" />
          </label>
          <label class="wide">
            <span>Model/Deployment IDs (comma-separated)</span>
            <input bind:value={connectionDraft.model_ids_text} placeholder="gpt-4o, gpt-4.1, my-deployment-name" />
          </label>
        </div>
      {/if}

      <div class="section-actions">
        <button class="admin-secondary" type="button" on:click={closeConnectionModal}>Cancel</button>
        <button class="admin-primary" type="button" disabled={connectionSaving} on:click={saveConnectionSettings}>{connectionSaving ? 'Saving...' : 'Save connection'}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .admin-shell {
    width: min(1180px, 100%);
    margin: 0 auto;
    padding: 6px 0 28px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .admin-tab-row,
  .admin-subtab-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }

  .admin-tab-row {
    border-bottom: 1px solid #242424;
    border-radius: 0;
    background: transparent;
    padding: 0 0 8px;
  }

  .admin-workspace {
    border: none;
    border-radius: 0;
    background: transparent;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .admin-tab-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .admin-tab-row button,
  .admin-subtab-row button,
  .admin-primary,
  .admin-secondary,
  .admin-icon-button,
  .admin-text-button {
    border: none;
    border-radius: 0;
    background: transparent;
    color: #9ca3af;
    padding: 6px 4px;
    font-family: inherit;
    font-size: 0.86rem;
    cursor: pointer;
  }

  .admin-tab-row button {
    border-bottom: 2px solid transparent;
    background: transparent;
    color: #a3a3a3;
    padding: 8px 10px;
  }

  .admin-tab-row button.active,
  .admin-subtab-row button.active {
    color: #ffffff;
    border-color: #ffffff;
  }

  .admin-panel-block {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .model-meta {
    display: grid;
    gap: 4px;
    color: #9ca3af;
    font-size: 0.82rem;
  }

  .admin-primary {
    color: #ffffff;
    font-weight: 500;
  }

  .admin-icon-button {
    width: auto;
    height: auto;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .admin-text-button {
    padding: 7px 10px;
    background: transparent;
  }

  .admin-stats {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 4px;
  }

  .admin-stat,
  .admin-card,
  .database-card,
  .stack-card,
  .group-card {
    border: none;
    border-radius: 0;
    background: transparent;
  }

  .admin-stat {
    padding: 2px 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .admin-stat span {
    font-size: 0.76rem;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .admin-stat strong {
    color: #d4d4d4;
    font-size: 0.88rem;
    font-weight: 500;
  }

  .admin-card {
    padding: 0;
  }

  .tab-section {
    border-radius: 0;
  }

  .tab-layout {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    gap: 40px;
  }

  .tab-sidebar {
    border: none;
    border-radius: 0;
    background: transparent;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .sidebar-nav {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .sidebar-nav button {
    border: none;
    border-radius: 0;
    background: transparent;
    color: #9ca3af;
    padding: 6px 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.84rem;
    text-align: left;
  }

  .sidebar-nav button strong {
    color: inherit;
    font-size: 0.78rem;
    border: none;
    border-radius: 0;
    padding: 0;
    font-weight: 600;
  }

  .sidebar-nav button.active {
    color: #ffffff;
  }

  .tab-main {
    min-width: 0;
    border-left: none;
    padding-left: 0;
  }

  .section-title-divider {
    height: 1px;
    background: #333333;
    margin: 8px 0 10px;
    width: 100%;
  }

  .sidebar-stats {
    grid-template-columns: 1fr;
  }

  .admin-card-wide {
    width: 100%;
    box-sizing: border-box;
  }

  .admin-card-head,
  .stack-card-head,
  .modal-head,
  .group-card-title-row,
  .member-row,
  .group-card,
  .admin-head-actions {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .admin-card h3,
  .modal-head h3,
  .group-card h4 {
    margin: 0;
    color: #f3f4f6;
  }

  .admin-copy,
  .modal-head p,
  .group-card p,
  .group-card-meta {
    margin: 6px 0 0;
    color: #9ca3af;
    font-size: 0.86rem;
    line-height: 1.45;
  }

  .admin-table {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .admin-table-row {
    display: grid;
    grid-template-columns: 120px 1.4fr 1.3fr 1.1fr 1.1fr;
    gap: 12px;
    padding: 9px 0;
    border-bottom: 1px solid #2a2a2a;
    color: #e5e7eb;
    font-size: 0.87rem;
  }

  .admin-table-head {
    color: #9ca3af;
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .admin-pill {
    border: none;
    border-radius: 0;
    padding: 0;
    color: #d1d5db;
    font-size: 0.74rem;
    white-space: nowrap;
  }

  .group-list,
  .stack-list,
  .permission-list,
  .member-list {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .group-card {
    padding: 10px 0;
    border-bottom: 1px solid #242424;
  }

  .group-card-main {
    flex: 1;
    min-width: 0;
  }

  .group-card-title-row {
    align-items: center;
  }

  .settings-form-grid {
    margin-top: 8px;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }

  .settings-form-grid label,
  .permission-row,
  .database-card,
  .stack-card {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .settings-form-grid label span,
  .database-card span {
    color: #c7c7c7;
    font-size: 0.82rem;
  }

  .settings-form-grid label.wide {
    grid-column: 1 / -1;
  }

  input,
  select,
  textarea {
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    background: #111111;
    color: #f3f4f6;
    padding: 8px 9px;
    font-family: inherit;
    font-size: 0.88rem;
    box-sizing: border-box;
    width: 100%;
  }

  textarea {
    resize: vertical;
  }

  .checkbox-row {
    flex-direction: row;
    align-items: center;
  }

  .checkbox-row input {
    width: 16px;
    height: 16px;
    padding: 0;
  }

  .checkbox-row.compact {
    justify-content: flex-end;
  }

  .permission-row {
    padding: 9px 0;
    border-bottom: 1px solid #272727;
  }

  .permission-row strong {
    color: #f3f4f6;
    text-transform: capitalize;
  }

  .section-actions,
  .member-toolbar {
    margin-top: 10px;
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    flex-wrap: wrap;
  }

  .database-grid {
    margin-top: 8px;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .database-card,
  .stack-card {
    padding: 10px 0;
    border-bottom: 1px solid #242424;
  }

  .database-card strong,
  .stack-card strong,
  .member-row strong {
    color: #f3f4f6;
  }

  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.58);
    backdrop-filter: blur(10px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    z-index: 150;
  }

  .modal-shell {
    width: min(760px, 100%);
    max-height: 88vh;
    overflow: auto;
    border: 1px solid #313131;
    border-radius: 22px;
    background: #171717;
    box-shadow: 0 32px 80px rgba(0, 0, 0, 0.45);
    padding: 20px;
    box-sizing: border-box;
  }

  .group-modal {
    width: min(920px, 100%);
  }

  .member-row {
    padding: 12px 0;
    border-bottom: 1px solid #272727;
  }

  .member-row:last-child {
    border-bottom: none;
  }

  .member-actions {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .admin-empty,
  .admin-notice {
    border: none;
    border-radius: 0;
    padding: 4px 0;
    color: #9ca3af;
    background: transparent;
  }

  .admin-notice.success {
    color: #9ca3af;
  }

  .admin-notice.error {
    color: #e5a3a3;
  }

  .connection-list {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .speaker-card {
    margin-top: 14px;
  }

  .speaker-list {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .speaker-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid #262626;
  }

  .speaker-main {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .speaker-main strong {
    color: #f3f4f6;
  }

  .speaker-main span {
    color: #9ca3af;
    font-size: 0.84rem;
    overflow-wrap: anywhere;
  }

  .connection-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding: 10px 0;
    border-bottom: 1px solid #262626;
  }

  .connection-main {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .connection-main strong {
    color: #f3f4f6;
  }

  .connection-main span {
    color: #9ca3af;
    font-size: 0.84rem;
    overflow-wrap: anywhere;
  }

  .connection-actions {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .switch {
    position: relative;
    display: inline-block;
    width: 42px;
    height: 24px;
  }

  .switch input {
    opacity: 0;
    width: 0;
    height: 0;
  }

  .slider {
    position: absolute;
    cursor: pointer;
    inset: 0;
    background: #2a2a2a;
    border-radius: 999px;
    transition: background 0.18s ease;
  }

  .slider::before {
    content: '';
    position: absolute;
    width: 18px;
    height: 18px;
    left: 3px;
    top: 3px;
    background: #a3a3a3;
    border-radius: 50%;
    transition: transform 0.18s ease, background 0.18s ease;
  }

  .switch input:checked + .slider {
    background: #16a34a;
  }

  .switch input:checked + .slider::before {
    transform: translateX(18px);
    background: #ffffff;
  }

  @media (max-width: 980px) {
    .tab-layout {
      grid-template-columns: 1fr;
    }

    .tab-main {
      border-left: none;
      border-top: none;
      padding-left: 0;
      padding-top: 0;
    }

    .admin-stats,
    .database-grid,
    .settings-form-grid {
      grid-template-columns: 1fr;
    }

    .admin-table-row {
      grid-template-columns: 1fr;
      gap: 6px;
    }

    .admin-card-head,
    .modal-head,
    .group-card,
    .member-row {
      flex-direction: column;
    }
  }

  :global(:root[data-theme='light']) .admin-tab-row,
  :global(:root[data-theme='light']) .group-card,
  :global(:root[data-theme='light']) .database-card,
  :global(:root[data-theme='light']) .stack-card,
  :global(:root[data-theme='light']) .speaker-row,
  :global(:root[data-theme='light']) .permission-row,
  :global(:root[data-theme='light']) .connection-row,
  :global(:root[data-theme='light']) .member-row {
    border-color: #d6d9df;
  }

  :global(:root[data-theme='light']) .section-title-divider {
    background: #d6d9df;
  }

  :global(:root[data-theme='light']) .admin-tab-row button,
  :global(:root[data-theme='light']) .admin-subtab-row button,
  :global(:root[data-theme='light']) .sidebar-nav button,
  :global(:root[data-theme='light']) .admin-stat span,
  :global(:root[data-theme='light']) .model-meta,
  :global(:root[data-theme='light']) .admin-copy,
  :global(:root[data-theme='light']) .modal-head p,
  :global(:root[data-theme='light']) .group-card p,
  :global(:root[data-theme='light']) .group-card-meta,
  :global(:root[data-theme='light']) .admin-table-head,
  :global(:root[data-theme='light']) .admin-empty,
  :global(:root[data-theme='light']) .admin-notice,
  :global(:root[data-theme='light']) .connection-main span,
  :global(:root[data-theme='light']) .speaker-main span,
  :global(:root[data-theme='light']) .settings-form-grid label span,
  :global(:root[data-theme='light']) .database-card span {
    color: #475569;
  }

  :global(:root[data-theme='light']) .admin-tab-row button.active,
  :global(:root[data-theme='light']) .admin-subtab-row button.active,
  :global(:root[data-theme='light']) .sidebar-nav button.active,
  :global(:root[data-theme='light']) .admin-primary,
  :global(:root[data-theme='light']) .admin-stat strong,
  :global(:root[data-theme='light']) .admin-card h3,
  :global(:root[data-theme='light']) .modal-head h3,
  :global(:root[data-theme='light']) .group-card h4,
  :global(:root[data-theme='light']) .admin-table-row,
  :global(:root[data-theme='light']) .database-card strong,
  :global(:root[data-theme='light']) .stack-card strong,
  :global(:root[data-theme='light']) .member-row strong,
  :global(:root[data-theme='light']) .permission-row strong,
  :global(:root[data-theme='light']) .speaker-main strong,
  :global(:root[data-theme='light']) .connection-main strong {
    color: #111827;
  }

  :global(:root[data-theme='light']) .admin-tab-row button.active,
  :global(:root[data-theme='light']) .admin-subtab-row button.active {
    border-color: #111827;
  }

  :global(:root[data-theme='light']) input,
  :global(:root[data-theme='light']) select,
  :global(:root[data-theme='light']) textarea {
    background: #ffffff;
    border-color: #d6d9df;
    color: #111827;
  }

  :global(:root[data-theme='light']) .slider {
    background: #cbd5e1;
  }

  :global(:root[data-theme='light']) .slider::before {
    background: #ffffff;
  }

  :global(:root[data-theme='light']) .modal-backdrop {
    background: rgba(148, 163, 184, 0.35);
  }

  :global(:root[data-theme='light']) .modal-shell {
    background: #ffffff;
    border-color: #d6d9df;
    box-shadow: 0 24px 56px rgba(15, 23, 42, 0.15);
  }
</style>