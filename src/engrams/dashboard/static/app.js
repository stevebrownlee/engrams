// ConPort Dashboard Application Logic
function dashboard() {
    return {
        // State
        view: 'overview',
        loading: false,
        searchQuery: '',
        searchResults: [],

        // Overview data
        stats: {},
        productContext: {},
        activeContext: {},
        recentActivity: [],
        features: { governance: false, bindings: false },

        // Decisions
        decisions: [],
        decisionSearch: '',
        detailModal: false,
        detailData: {},

        // Patterns
        patterns: [],

        // Progress
        progressItems: [],
        progressFilter: '',

        // Custom Data
        customDataItems: [],
        customCategories: [],
        customDataCategory: '',
        customDataSearch: '',

        // Graph
        graphFilters: {
            decision: true,
            system_pattern: true,
            progress: true,
            custom_data: true,
        },
        graphData: null,

        // Governance
        governanceData: { scopes: [], rules: [], amendments: [] },

        // Chat
        chatStatus: { enabled: false, available: false },
        chatMessages: [],
        chatInput: '',
        chatLoading: false,

        // Initialize
        async init() {
            await this.loadOverview();
            await this.checkChatStatus();
        },

        // Navigation
        async switchView(v) {
            this.view = v;
            switch (v) {
                case 'overview': await this.loadOverview(); break;
                case 'decisions': await this.loadDecisions(); break;
                case 'patterns': await this.loadPatterns(); break;
                case 'progress': await this.loadProgress(); break;
                case 'custom-data': await this.loadCustomData(); await this.loadCategories(); break;
                case 'graph': await this.loadGraph(); break;
                case 'governance': await this.loadGovernance(); break;
            }
        },

        // API helper
        async fetchApi(url) {
            try {
                const res = await fetch(url);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return await res.json();
            } catch (e) {
                console.error('API error:', e);
                return null;
            }
        },

        // Overview
        async loadOverview() {
            this.loading = true;
            try {
                const data = await this.fetchApi('/api/overview');
                if (data) {
                    this.stats = data.stats || {};
                    this.recentActivity = data.recent_activity || [];
                    this.features = data.stats?.features || {};
                }
                this.productContext = (await this.fetchApi('/api/product-context')) || {};
                this.activeContext = (await this.fetchApi('/api/active-context')) || {};
            } finally {
                this.loading = false;
            }
        },

        // Decisions
        async loadDecisions() {
            this.loading = true;
            try {
                let url = '/api/decisions?limit=200';
                if (this.decisionSearch) url += '&q=' + encodeURIComponent(this.decisionSearch);
                this.decisions = (await this.fetchApi(url)) || [];
            } finally {
                this.loading = false;
            }
        },

        async showDecisionDetail(id) {
            const data = await this.fetchApi(`/api/decisions/${id}`);
            if (data) {
                this.detailData = data;
                this.detailModal = true;
            }
        },

        // Patterns
        async loadPatterns() {
            this.loading = true;
            try {
                this.patterns = (await this.fetchApi('/api/patterns?limit=200')) || [];
            } finally {
                this.loading = false;
            }
        },

        async showPatternDetail(id) {
            const data = await this.fetchApi(`/api/patterns/${id}`);
            if (data) {
                this.detailData = data;
                this.detailModal = true;
            }
        },

        // Progress
        async loadProgress() {
            this.loading = true;
            try {
                let url = '/api/progress?limit=200';
                if (this.progressFilter) url += '&status=' + this.progressFilter;
                this.progressItems = (await this.fetchApi(url)) || [];
            } finally {
                this.loading = false;
            }
        },

        // Custom Data
        async loadCustomData() {
            this.loading = true;
            try {
                let url = '/api/custom-data?limit=200';
                if (this.customDataCategory) url += '&category=' + encodeURIComponent(this.customDataCategory);
                if (this.customDataSearch) url += '&q=' + encodeURIComponent(this.customDataSearch);
                this.customDataItems = (await this.fetchApi(url)) || [];
            } finally {
                this.loading = false;
            }
        },

        async loadCategories() {
            // Extract unique categories from custom data
            const data = await this.fetchApi('/api/custom-data?limit=1000');
            if (data) {
                const cats = new Set(data.map(d => d.category));
                this.customCategories = [...cats].sort();
            }
        },

        // Knowledge Graph
        async loadGraph() {
            const types = Object.entries(this.graphFilters)
                .filter(([, v]) => v)
                .map(([k]) => k);
            const url = types.length < 4
                ? '/api/graph?types=' + types.join(',')
                : '/api/graph';
            this.graphData = await this.fetchApi(url);
            if (this.graphData) {
                this.$nextTick(() => renderGraph(this.graphData));
            }
        },

        async updateGraph() {
            await this.loadGraph();
        },

        // Governance
        async loadGovernance() {
            this.loading = true;
            try {
                this.governanceData = (await this.fetchApi('/api/governance')) || { scopes: [], rules: [], amendments: [] };
            } finally {
                this.loading = false;
            }
        },

        // Global Search
        async globalSearch() {
            if (!this.searchQuery.trim()) return;
            this.view = 'search';
            this.loading = true;
            try {
                this.searchResults = (await this.fetchApi('/api/search?q=' + encodeURIComponent(this.searchQuery))) || [];
            } finally {
                this.loading = false;
            }
        },

        // Chat
        async checkChatStatus() {
            this.chatStatus = (await this.fetchApi('/api/chat/status')) || { enabled: false, available: false };
        },

        async sendChat() {
            if (!this.chatInput.trim() || this.chatLoading) return;
            const msg = this.chatInput.trim();
            this.chatInput = '';
            this.chatMessages.push({ role: 'user', content: msg });
            this.chatLoading = true;

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg }),
                });
                const data = await res.json();
                this.chatMessages.push({
                    role: 'assistant',
                    content: data.response || data.error || 'No response',
                    context_used: data.context_used || [],
                });
            } catch (e) {
                this.chatMessages.push({
                    role: 'assistant',
                    content: 'Error: ' + e.message,
                });
            } finally {
                this.chatLoading = false;
                this.$nextTick(() => {
                    const el = document.getElementById('chat-messages');
                    if (el) el.scrollTop = el.scrollHeight;
                });
            }
        },

        // Utility
        formatDate(dateStr) {
            if (!dateStr) return '';
            try {
                const d = new Date(dateStr);
                return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            } catch {
                return dateStr;
            }
        },
    };
}
