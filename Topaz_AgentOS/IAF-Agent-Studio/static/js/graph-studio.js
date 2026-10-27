/* Graph Studio tab, spread into skillStudio(); members are gs-prefixed methods (no getters: spread would freeze them). */
window.graphStudio = () => ({
    gsView: 'gallery',                 // 'gallery' | 'editor'
    gsGallerySearch: '',

    gsGraphName: '',
    gsGraphDesc: '',
    gsGraphKeywords: '',
    gsGraphCategory: 'platform',
    gsEditingName: null,               // null = create (POST); set = edit (PUT)

    gsGraph: { nodes: [], edges: [], converge: { enabled: false, max_loops: 3, on_exhausted: 'escalate_to_human' }, grounding: { independent_verifier: true } },
    gsGraphYaml: '',                   // derived-but-editable YAML view
    gsSelectedNodeId: null,

    gsYamlError: '',
    gsYamlFocused: false,
    gsSyncing: false,
    gsDiagramSeq: 0,
    _gsDiagramTimer: null,

    gsValidation: null,                // { ok, msg }

    gsNL: '',
    gsNLHistory: [],
    gsNLBusy: false,
    gsClarify: null,                   // { reply, questions[] }

    gsCheatOpen: false,
    gsYamlOpen: true,

    gsInit() {
        this._gsResetModel();
        this.gsView = 'gallery';
    },

    _gsResetModel() {
        this.gsGraph = {
            nodes: [],
            edges: [],
            converge: { enabled: false, max_loops: 3, on_exhausted: 'escalate_to_human' },
            grounding: { independent_verifier: true },
        };
        this.gsGraphName = '';
        this.gsGraphDesc = '';
        this.gsGraphKeywords = '';
        this.gsGraphCategory = 'platform';
        this.gsGraphYaml = '';
        this.gsSelectedNodeId = null;
        this.gsValidation = null;
        this.gsYamlError = '';
        this.gsClarify = null;
    },

    gsFilteredGraphs() {
        const q = (this.gsGallerySearch || '').toLowerCase();
        return (this.skills || [])
            .filter(s => (s.execution_mode || 'react') === 'graph')
            .filter(s => !q || (s.name || '').toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q));
    },

    gsLoadGallery() {
        this.gsView = 'gallery';
        try { this.loadSkills(); } catch (_) {}
    },

    gsSkillOptions() {
        return (this.skills || []).map(s => s.name).filter(Boolean).sort();
    },

    gsNewGraph() {
        this._gsResetModel();
        this.gsEditingName = null;
        // seed a friendly starting point
        this.gsApplyTemplate('parallel_verifier_escalate');
        this.gsView = 'editor';
    },

    async gsOpenGraph(name) {
        try {
            const res = await fetch(`/api/skills/${encodeURIComponent(name)}`);
            if (!res.ok) throw new Error('Not found');
            const d = await res.json();
            this._gsResetModel();
            this.gsEditingName = name;
            this.gsGraphName = d.name || name;
            this.gsGraphDesc = d.description || '';
            this.gsGraphKeywords = (d.keywords || []).join(', ');
            this.gsGraphCategory = d.category || 'platform';
            this.gsGraphYaml = d.graph_yaml || '';
            this.gsYamlToModel();          // parse YAML → model (also renders)
            this.gsView = 'editor';
            this.$nextTick(() => this.gsRenderDiagram());
        } catch (e) {
            this.showToast('error', 'Open failed', e.message);
        }
    },

    _gsBlankNode() {
        // unique-ish id
        let i = this.gsGraph.nodes.length + 1;
        let id = 'node_' + i;
        const used = new Set(this.gsGraph.nodes.map(n => n.id));
        while (used.has(id)) { i++; id = 'node_' + i; }
        return { id, skill: 'general', role: 'worker', task: '', verdict: { pass_when: 'PASS' } };
    },

    gsAddNode() {
        this.gsGraph.nodes.push(this._gsBlankNode());
        this.gsSync();
    },
    gsRemoveNode(idx) {
        const removed = this.gsGraph.nodes[idx];
        this.gsGraph.nodes.splice(idx, 1);
        // drop edges that reference the removed node
        if (removed) {
            const rid = removed.id;
            this.gsGraph.edges = this.gsGraph.edges.filter(e => e.to !== rid && !(e.from || []).includes(rid));
        }
        this.gsSync();
    },
    gsSetRole(node, role) {
        node.role = role;
        if (role === 'verifier' && !node.verdict) node.verdict = { pass_when: 'PASS' };
        this.gsSync();
    },
    gsAddEdge() {
        const ids = this.gsGraph.nodes.map(n => n.id);
        this.gsGraph.edges.push({ from: ids.length ? [ids[0]] : [], to: ids.length > 1 ? ids[1] : (ids[0] || ''), when: 'none' });
        this.gsSync();
    },
    gsRemoveEdge(idx) {
        this.gsGraph.edges.splice(idx, 1);
        this.gsSync();
    },
    gsNodeIds() {
        return this.gsGraph.nodes.map(n => n.id).filter(Boolean);
    },
    gsVerifierIds() {
        return this.gsGraph.nodes.filter(n => n.role === 'verifier').map(n => n.id);
    },

    gsSync() {
        if (this.gsSyncing) return;
        this.gsSyncing = true;
        try {
            if (!this.gsYamlFocused) {
                this.gsGraphYaml = this.gsModelToYaml();
                this.gsYamlError = '';
            }
        } catch (e) {
            this.gsYamlError = 'model→YAML error: ' + e.message;
        } finally {
            this.gsSyncing = false;
        }
        this._gsScheduleRender();
    },

    _gsScheduleRender() {
        if (this._gsDiagramTimer) clearTimeout(this._gsDiagramTimer);
        this._gsDiagramTimer = setTimeout(() => this.gsRenderDiagram(), 350);
    },

    gsModelToYaml() {
        const g = this.gsGraph;
        const obj = { apiVersion: 'agentos/process-graph/v1', name: this._gsSlug(this.gsGraphName) || 'my_graph' };
        obj.nodes = (g.nodes || []).map(n => {
            const nn = { id: n.id, skill: n.skill };
            if (n.role && n.role !== 'worker') nn.role = n.role;
            if (n.task) nn.task = n.task;
            if (n.role === 'verifier' && n.verdict && n.verdict.pass_when) nn.verdict = { pass_when: n.verdict.pass_when };
            return nn;
        });
        obj.edges = (g.edges || []).map(e => {
            const froms = (e.from || []).filter(Boolean);
            const ee = { from: froms.length === 1 ? froms[0] : froms, to: e.to };
            if (e.when && e.when !== 'none') ee.when = e.when;
            return ee;
        });
        if (g.converge && g.converge.enabled) {
            const conv = {};
            const verifier = this.gsVerifierIds()[0];
            if (verifier) { conv.until = `${verifier}.pass`; conv.scope = this.gsNodeIds(); }
            if (g.converge.max_loops) conv.max_loops = Number(g.converge.max_loops) || 3;
            if (g.converge.on_exhausted) conv.on_exhausted = g.converge.on_exhausted;
            obj.converge = conv;
        }
        if (g.grounding && g.grounding.independent_verifier) {
            obj.grounding = { independent_verifier: true };
        }
        return jsyaml.dump(obj, { indent: 2, lineWidth: -1 });
    },

    gsYamlToModel() {
        if (this.gsSyncing) return;
        this.gsSyncing = true;
        try {
            const parsed = jsyaml.load(this.gsGraphYaml);
            if (!parsed || typeof parsed !== 'object') throw new Error('empty');
            const nodes = (parsed.nodes || []).map(n => ({
                id: n.id || '',
                skill: n.skill || '',
                role: n.role || 'worker',
                task: n.task || '',
                verdict: { pass_when: (n.verdict && n.verdict.pass_when) || 'PASS' },
            }));
            const edges = (parsed.edges || []).map(e => ({
                from: Array.isArray(e.from) ? e.from : (e.from != null ? [e.from] : []),
                to: e.to != null ? e.to : '',
                when: e.when || 'none',
            }));
            const conv = parsed.converge || null;
            const grounding = parsed.grounding || null;
            this.gsGraph = {
                nodes, edges,
                converge: {
                    enabled: !!conv,
                    max_loops: (conv && conv.max_loops) || 3,
                    on_exhausted: (conv && conv.on_exhausted) || 'escalate_to_human',
                },
                grounding: { independent_verifier: grounding ? !!grounding.independent_verifier : true },
            };
            if (parsed.name && !this.gsGraphName) this.gsGraphName = parsed.name;
            this.gsYamlError = '';
        } catch (e) {
            // keep last-good model; surface a subtle hint; leave textarea untouched
            this.gsYamlError = 'waiting for valid YAML… (' + (e.message || 'parse error') + ')';
        } finally {
            this.gsSyncing = false;
        }
        this._gsScheduleRender();
    },

    async gsRenderDiagram() {
        const el = document.getElementById('gsDiagram');
        if (!el || typeof mermaid === 'undefined') return;
        const gy = (this.gsGraphYaml || '').trim();
        if (!gy) { el.innerHTML = '<span class="text-gray-600 text-xs">Add nodes to see the diagram…</span>'; return; }
        let src;
        try { src = this._graphToMermaid(gy); }
        catch (e) { return; }   // keep last good diagram while YAML is mid-edit
        const seq = ++this.gsDiagramSeq;
        try {
            mermaid.initialize({ startOnLoad: false, securityLevel: 'loose', theme: (this.themeMode === 'light' ? 'default' : 'dark') });
            const { svg } = await mermaid.render('gsdia_' + seq, src);
            if (seq !== this.gsDiagramSeq) return;   // a newer render superseded this one
            el.innerHTML = svg;
        } catch (e) {
            /* keep prior diagram */
        }
    },

    async gsValidate() {
        const gy = (this.gsGraphYaml || '').trim();
        if (!gy) { this.gsValidation = { ok: false, msg: 'Nothing to validate yet.' }; return; }
        this.gsValidation = { ok: true, msg: 'Validating…' };
        try {
            const res = await fetch('/api/designer/validate', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ envelope: {
                    artifact_type: 'graph_skill',
                    skill: { name: this._gsSlug(this.gsGraphName) || 'my_graph', execution_mode: 'graph' },
                    graph_yaml: gy } })
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok && data.ok) {
                this.gsValidation = { ok: true, msg: '✓ Graph is valid — compiles.' };
            } else {
                const errs = (data.errors && data.errors.length) ? data.errors.join('; ')
                    : (data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : 'Invalid graph');
                this.gsValidation = { ok: false, msg: '✕ ' + errs };
            }
        } catch (e) {
            this.gsValidation = { ok: false, msg: '✕ ' + e.message };
        }
    },

    _gsIsAdmin() { return (this.currentUser && this.currentUser.role === 'admin'); },
    _gsIsDev() { return this.currentUser && ['admin', 'developer', 'owner'].includes(this.currentUser.role); },

    async gsSaveGraph(opts = {}) {
        if (!this._gsIsAdmin()) { this.showToast('error', 'Admin required', 'Only admins can save graph skills.'); return false; }
        const name = this._gsSlug(this.gsGraphName);
        if (!name) { this.showToast('error', 'Name required', 'Give the graph a snake_case name.'); return false; }
        if (!(this.gsGraphYaml || '').trim() || !this.gsGraph.nodes.length) {
            this.showToast('error', 'Empty graph', 'Add at least one node before saving.'); return false;
        }
        // Populate the generic editor form and delegate to the existing, battle-tested saveSkill().
        const base = (typeof this._emptyForm === 'function') ? this._emptyForm() : {};
        this.editorForm = Object.assign(base, {
            name,
            description: this.gsGraphDesc || '',
            keywordsText: this.gsGraphKeywords || '',
            category: this.gsGraphCategory || 'platform',
            execution_mode: 'graph',
            graph_yaml: this.gsGraphYaml,
            graph_ref: 'graph.yaml',
        });
        this.editingName = this.gsEditingName || '';
        try {
            await this.saveSkill();
            await this.loadSkills();
            this.gsEditingName = name;     // subsequent saves become PUT
            if (!opts.stayInEditor) this.gsView = 'gallery';
            // Confirm it actually persisted (saveSkill may early-return on validation without throwing).
            return (this.skills || []).some(s => s.name === name);
        } catch (e) {
            this.showToast('error', 'Save failed', e.message);
            return false;
        }
    },

    // Run the graph currently open in the editor: save latest edits first (so the run reflects
    // what's on screen), then hand off to the main chat for live progress.
    async gsRunCurrent() {
        const name = this._gsSlug(this.gsGraphName);
        if (!name) { this.showToast('error', 'Name required', 'Give the graph a name first.'); return; }
        const ok = await this.gsSaveGraph({ stayInEditor: true });
        if (ok) this.gsRunGraph(name);
    },

    async gsCloneGraph(name) {
        if (!this._gsIsAdmin()) { this.showToast('error', 'Admin required', 'Only admins can clone.'); return; }
        const nn = this._gsSlug(prompt('Clone as (snake_case name):', name + '_copy') || '');
        if (!nn) return;
        try {
            const res = await fetch(`/api/skills/${encodeURIComponent(name)}/clone`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_name: nn })
            });
            if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Clone failed'); }
            await this.loadSkills();
            this.showToast('success', '✓ Cloned', `Created "${nn}".`);
        } catch (e) {
            this.showToast('error', 'Clone failed', e.message);
        }
    },

    async gsDeleteGraph(name) {
        if (!this._gsIsAdmin()) { this.showToast('error', 'Admin required', 'Only admins can delete.'); return; }
        if (!confirm(`Delete graph skill "${name}"? This cannot be undone.`)) return;
        try {
            const res = await fetch(`/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Delete failed'); }
            await this.loadSkills();
            this.showToast('success', '✓ Deleted', `Removed "${name}".`);
        } catch (e) {
            this.showToast('error', 'Delete failed', e.message);
        }
    },

    // Hand off to the main chat; it auto-sends the stashed "@name request" once the WebSocket connects.
    gsRunGraph(name) {
        const q = prompt(`Run "${name}" — what should it do?`, 'Run this process now');
        if (!q) return;
        try { localStorage.setItem('graph_run_task', `@${name} ${q}`); } catch (_) {}
        // Served at {ROOT_PATH}/skill-builder/v2 without a trailing slash, so the relative '../' resolves to the chat root.
        window.location.assign('../');
    },

    async gsDraftFromNL() {
        const msg = (this.gsNL || '').trim();
        if (!msg || this.gsNLBusy) return;
        if (!this._gsIsDev()) { this.showToast('error', 'Dev role required', 'Draft-with-AI needs a developer/admin/owner role.'); return; }
        this.gsNLBusy = true;
        this.gsClarify = null;
        this.gsNLHistory.push({ role: 'user', content: msg });
        try {
            const res = await fetch('/api/designer/chat', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg, history: this.gsNLHistory.slice(-7, -1), artifact_hint: 'graph_skill' })
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data.detail && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))) || ('HTTP ' + res.status));
            const env = data.envelope || {};
            if (env.artifact_type === 'graph_skill' && env.graph_yaml) {
                this.gsGraphYaml = env.graph_yaml;
                if (env.name && !this.gsGraphName) this.gsGraphName = env.name;
                if (env.summary && !this.gsGraphDesc) this.gsGraphDesc = env.summary;
                this.gsYamlToModel();
                this.$nextTick(() => this.gsRenderDiagram());
                this.gsNLHistory.push({ role: 'assistant', content: env.reply || env.summary || 'Drafted the graph — review it below.' });
                this.gsNL = '';
            } else {
                // clarify (or non-graph) turn — show the question, don't touch the model
                const reply = env.reply || env.summary || 'Could you clarify the graph you want?';
                this.gsClarify = { reply, questions: env.questions || [] };
                this.gsNLHistory.push({ role: 'assistant', content: reply });
            }
        } catch (e) {
            this.showToast('error', 'Draft failed', e.message);
            this.gsNLHistory.push({ role: 'assistant', content: '⚠ ' + e.message });
        } finally {
            this.gsNLBusy = false;
        }
    },

    gsApplyTemplate(kind) {
        const mk = (id, skill, role, task, extra) => Object.assign({ id, skill: skill || 'general', role: role || 'worker', task: task || '', verdict: { pass_when: 'PASS' } }, extra || {});
        let g;
        if (kind === 'blank') {
            g = { nodes: [mk('step_1', 'general', 'worker', 'Do the first thing')], edges: [], converge: { enabled: false, max_loops: 3, on_exhausted: 'escalate_to_human' }, grounding: { independent_verifier: true } };
        } else if (kind === 'linear') {
            g = { nodes: [mk('collect', 'general', 'worker', 'Collect inputs'), mk('analyze', 'general', 'worker', 'Analyze {{collect.result}}'), mk('summarize', 'general', 'worker', 'Summarize {{analyze.result}}')],
                  edges: [{ from: ['collect'], to: 'analyze', when: 'none' }, { from: ['analyze'], to: 'summarize', when: 'none' }],
                  converge: { enabled: false, max_loops: 3, on_exhausted: 'escalate_to_human' }, grounding: { independent_verifier: true } };
        } else if (kind === 'convergence') {
            g = { nodes: [mk('work', 'general', 'worker', 'Attempt the task'), mk('verify', 'general', 'verifier', 'Review {{work.result}}; reply PASS or FAIL with reasons')],
                  edges: [{ from: ['work'], to: 'verify', when: 'none' }],
                  converge: { enabled: true, max_loops: 3, on_exhausted: 'escalate_to_human' }, grounding: { independent_verifier: true } };
        } else { // parallel_verifier_escalate (default)
            g = { nodes: [mk('branch_a', 'general', 'worker', 'Gather source A'), mk('branch_b', 'general', 'worker', 'Gather source B'),
                          mk('verify', 'general', 'verifier', 'Review {{branch_a.result}} and {{branch_b.result}}; reply PASS or FAIL'),
                          mk('briefing', 'general', 'worker', 'Summarize {{branch_a.result}} and {{branch_b.result}}')],
                  edges: [{ from: ['branch_a', 'branch_b'], to: 'verify', when: 'none' }, { from: ['verify'], to: 'briefing', when: 'pass' }],
                  converge: { enabled: true, max_loops: 3, on_exhausted: 'escalate_to_human' }, grounding: { independent_verifier: true } };
        }
        this.gsGraph = g;
        this.gsSync();
        this.$nextTick(() => this.gsRenderDiagram());
    },

    _gsSlug(s) {
        return (s || '').toString().trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 63);
    },
});
