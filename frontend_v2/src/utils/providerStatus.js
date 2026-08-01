const ONLINE_RUNTIME_STATUSES = new Set(['running', 'active', 'connected', 'discovered']);
const TRANSITION_RUNTIME_STATUSES = new Set(['starting', 'stopping', 'restarting']);
const RECONCILIATION_QUEUED = new Set(['started', 'queued']);
const RECONCILIATION_ACTIVE = new Set(['progress', 'running', 'reconciling']);

function asObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function asArray(value) {
    return Array.isArray(value) ? value : [];
}

function asCount(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric > 0 ? Math.floor(numeric) : 0;
}

function humanize(value, fallback = 'Unknown') {
    if (!value) return fallback;
    return String(value).replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function normalizeReconciliationStatus(status) {
    if (RECONCILIATION_QUEUED.has(status)) {
        return 'queued';
    }
    if (RECONCILIATION_ACTIVE.has(status)) {
        return 'reconciling';
    }
    return status || 'idle';
}

function normalizeActionLabel(actionLabel) {
    if (!actionLabel) return '';
    return humanize(actionLabel, '').trim();
}

function pluralize(count, noun) {
    return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

export function summarizeProviderStatus(
    provider,
    {
        actionLabel = null,
        jobsAssigned = 0,
        providerFailures = 0,
    } = {},
) {
    const safeProvider = asObject(provider);
    const runtime = asObject(safeProvider.runtime_state);
    const deploy = asObject(safeProvider.deploy_state);
    const reconciliation = asObject(safeProvider.reconciliation_state);
    const reconciliationStats = asObject(reconciliation.stats);
    const diagnostics = asObject(safeProvider.diagnostics);
    const modelSync = asObject(safeProvider.model_sync);
    const modelSyncStats = asObject(modelSync.stats);

    const warningCount = asArray(diagnostics.warnings).length;
    const errorCount = asArray(diagnostics.errors).length;
    const runtimeStatus = runtime.status || (runtime.connected ? 'active' : 'stopped');
    const deployStatus = deploy.status || 'idle';
    const reconciliationStatus = normalizeReconciliationStatus(reconciliation.status);

    let downloadsActive = Math.max(
        asCount(modelSyncStats.downloading),
        asArray(reconciliation.active_downloads).length,
        asCount(reconciliationStats.downloads_in_progress),
    );
    let downloadsQueued = Math.max(
        asCount(modelSyncStats.pending),
        asCount(reconciliationStats.downloads_queued),
    );
    let downloadsCompleted = asCount(reconciliationStats.downloads_completed);

    if (safeProvider.worker_type === 'llm') {
        downloadsActive = 0;
        downloadsQueued = 0;
        downloadsCompleted = 0;
    }

    const summary = {
        runtimeStatus,
        deployStatus,
        reconciliationStatus,
        isDisabled: !safeProvider.enabled,
        isOnline: safeProvider.enabled && ONLINE_RUNTIME_STATUSES.has(runtimeStatus),
        warningCount,
        errorCount,
        downloadsActive,
        downloadsQueued,
        downloadsCompleted,
        jobsAssigned: asCount(jobsAssigned),
        providerFailures: asCount(providerFailures),
        stage: 'offline',
        label: 'Offline',
        message: '',
        dotTone: 'offline',
        actionLabel: normalizeActionLabel(actionLabel),
    };

    if (summary.isDisabled) {
        summary.stage = 'disabled';
        summary.label = 'Disabled';
        summary.message = 'Provider disabled';
        summary.dotTone = 'offline';
        return summary;
    }

    if (summary.actionLabel) {
        summary.stage = 'action';
        summary.label = summary.actionLabel;
        summary.message = 'Request in progress';
        summary.dotTone = 'working';
        return summary;
    }

    if (deployStatus === 'deploying') {
        summary.stage = 'deploying';
        summary.label = 'Deploying';
        summary.message = deploy.message || 'Deployment in progress';
        summary.dotTone = 'deploying';
        return summary;
    }

    if (deployStatus === 'failed') {
        summary.stage = 'deploy_failed';
        summary.label = 'Deploy Failed';
        summary.message = deploy.message || 'Deployment failed';
        summary.dotTone = 'failed';
        return summary;
    }

    if (reconciliationStatus === 'queued' || reconciliationStatus === 'reconciling') {
        summary.stage = 'syncing';
        summary.label = reconciliationStatus === 'queued' ? 'Sync Queued' : 'Syncing';
        if (summary.downloadsActive > 0) {
            summary.message = `${pluralize(summary.downloadsActive, 'download')} active`;
        } else if (summary.downloadsQueued > 0) {
            summary.message = `${pluralize(summary.downloadsQueued, 'download')} queued`;
        } else {
            summary.message = reconciliation.message || 'Reconciling provider model state';
        }
        summary.dotTone = 'syncing';
        return summary;
    }

    if (summary.downloadsActive > 0) {
        summary.stage = 'downloading';
        summary.label = 'Downloading';
        summary.message = `${pluralize(summary.downloadsActive, 'download')} active`;
        summary.dotTone = 'downloading';
        return summary;
    }

    if (summary.errorCount > 0 || summary.providerFailures > 0) {
        const issueCount = summary.errorCount + summary.providerFailures;
        summary.stage = 'error';
        summary.label = 'Attention';
        summary.message = `${pluralize(issueCount, 'issue')} detected`;
        summary.dotTone = 'failed';
        return summary;
    }

    if (summary.warningCount > 0) {
        summary.stage = 'warning';
        summary.label = 'Warning';
        summary.message = `${pluralize(summary.warningCount, 'warning')} present`;
        summary.dotTone = 'warning';
        return summary;
    }

    if (TRANSITION_RUNTIME_STATUSES.has(runtimeStatus)) {
        summary.stage = 'runtime_transition';
        summary.label = humanize(runtimeStatus);
        summary.message = 'Container transition in progress';
        summary.dotTone = 'working';
        return summary;
    }

    if (summary.isOnline) {
        summary.stage = 'online';
        summary.label = 'Running';
        summary.message = runtime.connected ? 'Connected' : '';
        summary.dotTone = 'online';
        return summary;
    }

    summary.stage = runtimeStatus === 'configured' ? 'configured' : 'offline';
    summary.label = humanize(runtimeStatus, 'Offline');
    summary.message = runtimeStatus === 'configured' ? 'Configured but not running' : '';
    summary.dotTone = 'offline';
    return summary;
}

export function providerDotToneClass(tone) {
    const map = {
        online: 'online',
        offline: 'offline',
        deploying: 'deploying',
        syncing: 'syncing',
        downloading: 'downloading',
        warning: 'warning',
        failed: 'failed',
        working: 'working',
    };
    return map[tone] || map.offline;
}

export function providerTextToneClass(stage) {
    const map = {
        online: 'text-gray-300',
        deploying: 'text-purple-200',
        syncing: 'text-blue-200',
        downloading: 'text-cyan-200',
        warning: 'text-amber-200',
        error: 'text-red-200',
        deploy_failed: 'text-red-200',
        disabled: 'text-gray-600',
        action: 'text-sky-200',
        runtime_transition: 'text-sky-200',
        configured: 'text-gray-400',
        offline: 'text-gray-500',
    };
    return map[stage] || map.offline;
}

export function providerBadgeToneClass(stage) {
    const map = {
        online: 'border-green-500/25 bg-green-500/10 text-green-300',
        deploying: 'border-purple-500/25 bg-purple-500/10 text-purple-300',
        syncing: 'border-blue-500/25 bg-blue-500/10 text-blue-300',
        downloading: 'border-cyan-500/25 bg-cyan-500/10 text-cyan-300',
        warning: 'border-amber-500/25 bg-amber-500/10 text-amber-300',
        error: 'border-red-500/25 bg-red-500/10 text-red-300',
        deploy_failed: 'border-red-500/25 bg-red-500/10 text-red-300',
        disabled: 'border-gray-600/40 bg-gray-700/20 text-gray-500',
        action: 'border-sky-500/25 bg-sky-500/10 text-sky-300',
        runtime_transition: 'border-sky-500/25 bg-sky-500/10 text-sky-300',
        configured: 'border-gray-600/40 bg-gray-700/20 text-gray-400',
        offline: 'border-gray-600/40 bg-gray-700/20 text-gray-400',
    };
    return map[stage] || map.offline;
}
