    (() => {
      'use strict';

      const $ = (selector) => document.querySelector(selector);
      let serverConfig = {};
      try { serverConfig = JSON.parse($('#serverConfig').textContent) || {}; } catch (_) {}
      const params = new URLSearchParams(location.search);
      const config = {
        refreshMs: Math.max(10, Number(params.get('refresh')) || 30) * 1000,
        firstPageMs: Math.max(5, Number(params.get('firstPageTime')) || 120) * 1000,
        pageMs: Math.max(5, Number(params.get('pageTime')) || 30) * 1000,
        recentSolveMs: Math.max(30, Number(params.get('recentSolveTime')) || 240) * 1000,
        count: Math.min(500, Math.max(20, Number(params.get('count')) || 200)),
        showUnofficial: params.get('unofficial') !== 'false'
      };

      const sourceLabels = { codeforces: 'Codeforces', opentrains: 'OpenTrains', domjudge: 'DOMjudge' };
      function canonicalSource(value) { return value === 'opencup' ? 'opentrains' : (sourceLabels[value] ? value : 'codeforces'); }
      const initialSource = canonicalSource(String(params.get('source') || (params.has('contest') ? 'codeforces' : '') || localStorage.getItem('icpc-source') || serverConfig.source || 'codeforces').toLowerCase());
      const sourceDefaults = serverConfig.sources || { [canonicalSource(serverConfig.source)]: serverConfig };
      const initialDefaults = sourceDefaults[initialSource] || {};
      const initialStandingsUrl = (initialSource === 'codeforces' ? params.get('contest') : '') || params.get('url') || localStorage.getItem(`icpc-${initialSource}-url`) || (initialSource === 'opentrains' ? localStorage.getItem('icpc-opencup-url') : '') || String(initialDefaults.standingsUrl || initialDefaults.opencupUrl || '');
      const explicitContest = params.has('contest') || params.has('url');
      const initialGroup = params.get('group') || (!explicitContest && initialSource === 'codeforces'
        ? savedCodeforcesGroup(initialDefaults) : '');
      // API credentials from older versions are no longer used or retained.
      for (const key of ['icpc-api-key', 'icpc-api-secret']) {
        sessionStorage.removeItem(key);
        localStorage.removeItem(key);
      }
      const state = {
        source: initialSource || 'codeforces',
        sourceLabel: sourceLabels[initialSource],
        universityAliases: readSavedAliases(),
        standingsUrl: initialStandingsUrl,
        groupCode: initialSource === 'codeforces' ? initialGroup : '',
        showGhosts: initialGhostSetting(),
        scoring: ScoreboardScoring.forContest(),
        ioiMaximum: readIOIMaximum(),
        contest: null,
        problems: [],
        rows: [],
        recentSolves: new Map(),
        currentPage: 0,
        rowsPerPage: 8,
        problemsPerPage: 1,
        pageTimer: null,
        refreshTimer: null,
        clockTimer: null,
        loading: false,
        requestId: 0,
        controller: null,
        demo: false,
        lastUpdated: null
      };

      const els = {
        contestName: $('#contestName'), phasePill: $('#phasePill'), contestIdMeta: $('#contestIdMeta'),
        teamCount: $('#teamCount'), demoBadge: $('#demoBadge'), timerLabel: $('#timerLabel'),
        contestTimer: $('#contestTimer'), standingsBody: $('#standingsBody'),
        tableHead: $('#tableHead'), colgroup: $('#colgroup'), emptyState: $('#emptyState'),
        scoreboard: document.querySelector('.scoreboard'),
        syncStatus: $('#syncStatus'), syncText: $('#syncText'), pageDots: $('#pageDots'),
        setupDialog: $('#setupDialog'), setupForm: $('#setupForm'), contestInput: $('#contestInput'),
        sourceSelect: $('#sourceSelect'), groupInput: $('#groupInput'), ghostsInput: $('#ghostsInput'), aliasesInput: $('#aliasesInput'),
        ioiMaximumInput: $('#ioiMaximumInput'), scoreboardLabel: $('#scoreboardLabel'),
        dialogError: $('#dialogError'), refreshButton: $('#refreshButton'), settingsButton: $('#settingsButton'),
        fullscreenButton: $('#fullscreenButton'), previewButton: $('#previewButton')
      };
      els.provider = document.querySelector('.provider');

      $('#refreshSeconds').textContent = String(config.refreshMs / 1000);

      function readSavedAliases() {
        try {
          const aliases = JSON.parse(localStorage.getItem('icpc-university-aliases') || 'null');
          if (aliases && typeof aliases === 'object' && !Array.isArray(aliases)) {
            return { ...serverConfig.universityAliases, ...aliases };
          }
        } catch (_) {}
        return serverConfig.universityAliases || {};
      }

      function readIOIMaximum() {
        const value = Number(params.get('ioiMaxPoints') || (!explicitContest && localStorage.getItem('icpc-ioi-maximum')) || 100);
        return Number.isFinite(value) && value > 0 ? value : 100;
      }

      function initialGhostSetting() {
        return params.has('ghosts') ? params.get('ghosts') === 'true'
          : !explicitContest && localStorage.getItem('icpc-codeforces-ghosts') === 'true';
      }

      function savedCodeforcesGroup(defaults) {
        return localStorage.getItem('icpc-codeforces-url')
          ? localStorage.getItem('icpc-codeforces-group') || '' : defaults.groupCode || '';
      }

      function codeforcesTarget(value, group = '') {
        value = String(value || '').trim();
        group = String(group || '').trim();
        if (group && !/^[A-Za-z0-9]{1,64}$/.test(group)) throw new Error('Enter a valid Codeforces group code.');
        let id = /^[1-9]\d{0,8}$/.test(value) ? value : '';
        if (!id) {
          const match = value.match(/^https?:\/\/(?:www\.)?codeforces\.com(?::(?:80|443))?\/(?:group\/([A-Za-z0-9]{1,64})\/)?(?:contest|gym)\/([1-9]\d{0,8})(?:\/(?:standings|problems|status))?\/?(?:[?#].*)?$/);
          if (!match) throw new Error('Enter a Codeforces contest ID or contest URL, not a spectator ranklist.');
          if (match[1] && group && match[1] !== group) throw new Error('The group code does not match the contest URL.');
          id = match[2];
          group = match[1] || group;
        }
        return { id, group, url: group ? `https://codeforces.com/group/${group}/contest/${id}` : `https://codeforces.com/contest/${id}` };
      }

      function contestDisplayValue() {
        return state.standingsUrl || '';
      }

      function formatDuration(totalSeconds) {
        const seconds = Math.max(0, Math.floor(totalSeconds));
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const remainder = seconds % 60;
        return [hours, minutes, remainder].map((part) => String(part).padStart(2, '0')).join(':');
      }

      function formatClock(date) {
        return new Intl.DateTimeFormat(undefined, {
          hour: '2-digit', minute: '2-digit', second: '2-digit'
        }).format(date);
      }

      function formatProblemTime(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) return '';
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const rest = minutes % 60;
        return hours ? `${hours}:${String(rest).padStart(2, '0')}` : `${minutes} min`;
      }

      function participantKey(row) {
        if (row.party.ghost === true) return `ghost:${row.party.contestId}:${row.party.participantId ?? row.party.teamId ?? row.party.teamName}`;
        return row.party.teamId ? `team:${row.party.teamId}` : row.party.members.map((member) => member.handle).join('|');
      }

      function participantName(row) {
        if (row.party.teamName) return row.party.teamName;
        if (row.party.participantType === 'VIRTUAL') return `${row.party.members[0]?.handle || 'Virtual'} (virtual)`;
        return row.party.members.map((member) => member.name || member.handle).join(', ') || 'Unknown participant';
      }

      function participantMembers(row) {
        if (row.party.ghost === true) return 'Original contest';
        if (!row.party.teamName && row.party.members?.some(member => member.name && member.name !== member.handle)) {
          return row.party.members.map(member => member.handle).join(' · ');
        }
        if (!row.party.teamName || !row.party.members?.length) {
          const type = String(row.party.participantType || '').toLowerCase();
          return type && type !== 'contestant' ? type : '';
        }
        return row.party.members.map((member) => member.handle).join(' · ');
      }

      function splitStructuredTeamName(teamName) {
        const value = String(teamName || '').trim();
        const match = value.match(/^([^:]+):\s*(.*?)\s*\(([^()]*)\)\s*$/);
        if (match) {
          return {
            university: match[1].trim(),
            name: match[2].trim(),
            participants: match[3].trim()
          };
        }
        const teamOnlyMatch = value.match(/^(.*?)\s*\(([^()]*)\)\s*$/);
        if (!teamOnlyMatch) return null;
        return {
          university: '',
          name: teamOnlyMatch[1].trim(),
          participants: teamOnlyMatch[2].trim()
        };
      }

      function participantDisplay(row) {
        const fullName = participantName(row);
        if (Object.prototype.hasOwnProperty.call(row.party, 'university')) {
          const fullUniversity = row.party.university;
          const university = state.universityAliases[fullUniversity] || fullUniversity;
          return {
            name: university ? `${university}: ${fullName}` : fullName,
            details: participantMembers(row),
            title: fullUniversity ? `${fullUniversity}: ${fullName}` : fullName
          };
        }
        const structured = row.party.teamName ? splitStructuredTeamName(row.party.teamName) : null;
        if (structured) {
          const university = structured.university ? state.universityAliases[structured.university] || structured.university : '';
          return {
            name: university ? `${university}: ${structured.name}` : structured.name,
            details: structured.participants,
            title: fullName
          };
        }
        return {
          name: fullName,
          details: participantMembers(row) || (row.party.ghost ? 'Out of competition' : 'Official participant'),
          title: fullName
        };
      }

      function newlySolvedProblemIndices(previousRow, currentRow) {
        if (!previousRow) return [];
        const indices = [];
        currentRow.problemResults?.forEach((problem, index) => {
          if (state.scoring.improved(previousRow.problemResults?.[index], problem)) indices.push(index);
        });
        return indices;
      }

      function setSync(mode, message) {
        els.syncStatus.className = `sync-status ${mode || ''}`.trim();
        els.syncText.textContent = message;
      }

      function updateClock() {
        if (!state.contest) {
          els.contestTimer.textContent = '--:--:--';
          return;
        }
        if (Number.isFinite(state.contest.remainingTimeSeconds) && state.contest.phase !== 'FINISHED') {
          els.timerLabel.textContent = state.contest.phase === 'BEFORE' ? 'Starts in' : 'Time remaining';
          const sinceFetch = Math.max(0, (Date.now() - state.receivedAt) / 1000);
          els.contestTimer.textContent = formatDuration(state.contest.remainingTimeSeconds - sinceFetch);
          return;
        }
        if (state.contest.timingAvailable === false) {
          els.timerLabel.textContent = 'Contest time';
          els.contestTimer.textContent = '--:--:--';
          return;
        }

        const start = Number(state.contest.startTimeSeconds || 0);
        const duration = Number(state.contest.durationSeconds || 0);
        const nowSeconds = Date.now() / 1000;
        const elapsed = nowSeconds - start;
        const phase = state.contest.phase;

        if (phase === 'BEFORE' || elapsed < 0) {
          els.timerLabel.textContent = 'Starts in';
          els.contestTimer.textContent = formatDuration(-elapsed);
        } else if (phase === 'FINISHED') {
          els.timerLabel.textContent = 'Contest duration';
          els.contestTimer.textContent = formatDuration(duration);
        } else {
          els.timerLabel.textContent = 'Contest time';
          els.contestTimer.textContent = formatDuration(Math.min(Math.max(elapsed, 0), duration || elapsed));
        }
      }

      function setPhase(phase) {
        const normalized = String(phase || '').toUpperCase();
        els.phasePill.className = 'phase-pill';
        if (!normalized) {
          els.phasePill.classList.add('pending');
          els.phasePill.textContent = 'Setup';
        } else if (normalized === 'FINISHED') {
          els.phasePill.classList.add('finished');
          els.phasePill.textContent = 'Final';
        } else if (normalized === 'BEFORE') {
          els.phasePill.classList.add('pending');
          els.phasePill.textContent = 'Upcoming';
        } else {
          els.phasePill.textContent = 'Live';
        }
      }

      function updateColumnLayout() {
        const width = Math.max(1, els.scoreboard.clientWidth - 2);
        const rankWidth = Math.min(88, Math.max(68, width * .042));
        const solvedWidth = Math.min(104, Math.max(88, width * .052));
        const penaltyWidth = state.scoring.columns.some(column => column.field === 'penalty')
          ? Math.min(124, Math.max(104, width * .06)) : 0;
        const fixedWidth = rankWidth + solvedWidth + penaltyWidth;
        const desiredTeamWidth = Math.min(620, Math.max(300, width * .3));
        const minimumTeamWidth = Math.min(360, Math.max(230, width * .2));
        const minimumProblemWidth = width >= 1500 ? 58 : width >= 1100 ? 50 : 48;
        const problemCount = state.problems.length;
        const maximumProblems = Math.max(1, Math.floor((width - fixedWidth - minimumTeamWidth) / minimumProblemWidth));
        state.problemsPerPage = problemCount ? Math.min(problemCount, maximumProblems) : 1;

        let problemWidth = problemCount
          ? (width - fixedWidth - desiredTeamWidth) / state.problemsPerPage
          : minimumProblemWidth;
        problemWidth = Math.min(84, Math.max(minimumProblemWidth, problemWidth));
        let teamWidth = width - fixedWidth - problemWidth * (problemCount ? state.problemsPerPage : 0);

        if (teamWidth < minimumTeamWidth && problemCount) {
          teamWidth = minimumTeamWidth;
          problemWidth = (width - fixedWidth - teamWidth) / state.problemsPerPage;
        }

        const rootStyle = document.documentElement.style;
        rootStyle.setProperty('--rank-size', `${rankWidth}px`);
        rootStyle.setProperty('--solved-size', `${solvedWidth}px`);
        rootStyle.setProperty('--penalty-size', `${penaltyWidth}px`);
        rootStyle.setProperty('--team-size', `${Math.max(120, teamWidth)}px`);
        rootStyle.setProperty('--problem-size', `${Math.max(42, problemWidth)}px`);
        els.scoreboard.classList.toggle('compact-problems', problemWidth < 62);
      }

      function buildHeader(problemIndices) {
        els.tableHead.replaceChildren();
        els.colgroup.replaceChildren();

        const columns = [
          ['rank-col', '#', 'Rank'], ['team-col', state.scoring.participantLabel, state.scoring.id === 'IOI' ? 'Name / Handle' : 'Participants'],
          ...state.scoring.columns.map(column => [column.className, column.label, column.sub])
        ];

        columns.forEach(([className, primary, sub]) => {
          const col = document.createElement('col');
          col.className = className;
          els.colgroup.appendChild(col);
          const th = document.createElement('th');
          th.className = className;
          const primarySpan = document.createElement('span');
          primarySpan.className = 'th-primary';
          primarySpan.textContent = primary;
          const subSpan = document.createElement('span');
          subSpan.className = 'th-sub';
          subSpan.textContent = sub;
          th.append(primarySpan, subSpan);
          els.tableHead.appendChild(th);
        });

        problemIndices.forEach((problemIndex) => {
          const problem = state.problems[problemIndex];
          const col = document.createElement('col');
          col.className = 'problem-col';
          els.colgroup.appendChild(col);
          const th = document.createElement('th');
          th.className = 'problem-col';
          th.title = problem.name || `Problem ${problem.index}`;
          const primarySpan = document.createElement('span');
          primarySpan.className = 'th-primary';
          primarySpan.textContent = problem.index;
          th.appendChild(primarySpan);
          if (state.scoring.id === 'IOI') {
            const maximum = document.createElement('span');
            maximum.className = 'th-sub';
            maximum.textContent = `${ScoreboardScoring.formatScore(ScoreboardScoring.maximum(problem, state.ioiMaximum))} max`;
            th.appendChild(maximum);
          }
          els.tableHead.appendChild(th);
        });
      }

      function makeRankCell(row) {
        const td = document.createElement('td');
        td.className = 'rank-col';
        const rank = Number(row.rank);
        if (rank >= 1 && rank <= 3) {
          const badge = document.createElement('span');
          badge.className = `medal ${rank === 2 ? 'silver' : rank === 3 ? 'bronze' : ''}`.trim();
          badge.textContent = String(rank);
          td.appendChild(badge);
        } else {
          const span = document.createElement('span');
          span.className = 'rank-number';
          span.textContent = String(row.rank ?? '—');
          td.appendChild(span);
        }
        return td;
      }

      function makeTeamCell(row, recentProblemLabels = []) {
        const td = document.createElement('td');
        td.className = 'team-cell team-col';
        const display = participantDisplay(row);
        const heading = document.createElement('div');
        heading.className = 'team-heading';
        if (row.party.ghost === true) {
          const marker = document.createElement('span');
          marker.className = 'ghost-marker';
          marker.textContent = '👻';
          marker.title = 'Ghost from original contest';
          marker.setAttribute('role', 'img');
          marker.setAttribute('aria-label', marker.title);
          heading.appendChild(marker);
        }
        const name = document.createElement('div');
        name.className = 'team-name';
        name.textContent = display.name;
        name.title = display.title;
        heading.appendChild(name);
        if (recentProblemLabels.length) {
          const badge = document.createElement('span');
          badge.className = 'recent-solve-badge';
          badge.textContent = `${state.scoring.recentLabel} ${recentProblemLabels.join(', ')}`;
          heading.appendChild(badge);
        }
        const members = document.createElement('div');
        members.className = 'team-members';
        members.textContent = display.details;
        members.title = display.title;
        td.append(heading, members);
        return td;
      }

      function makeScoreCell(value, className, formatter = String) {
        const td = document.createElement('td');
        td.className = className;
        const span = document.createElement('span');
        span.className = className === 'solved-col' ? 'score-main' : 'penalty-main';
        span.textContent = formatter(value);
        span.title = span.textContent;
        if (span.textContent.length > 5) span.classList.add('long-score');
        td.appendChild(span);
        return td;
      }

      function makeProblemCell(result, hasRecentSolve = false, problem) {
        const td = document.createElement('td');
        td.className = 'problem-cell problem-col';
        if (hasRecentSolve) td.classList.add('recent-solve-cell');
        const box = document.createElement('div');
        const presentation = state.scoring.problem(result, problem, state.ioiMaximum);
        box.className = `problem-result ${presentation.status} ${presentation.first ? 'first-to-solve' : ''}`.trim();
        if (presentation.preliminary) box.classList.add('preliminary');
        if (state.scoring.id === 'IOI') {
          box.title = `${presentation.text} / ${ScoreboardScoring.formatScore(presentation.maximum)}${presentation.preliminary ? ' (preliminary)' : ''}`;
        }

        const score = document.createElement('div');
        score.className = 'problem-score';
        score.textContent = presentation.text;
        score.title = presentation.text;
        if (presentation.text.length > 5) score.classList.add('long-score');
        box.appendChild(score);

        const detail = presentation.detail || (presentation.preliminary ? 'Pending' : '')
          || (Number.isFinite(presentation.time) ? formatProblemTime(presentation.time) : '');
        if (detail) {
          const time = document.createElement('div');
          time.className = 'problem-time';
          time.textContent = detail;
          box.appendChild(time);
        }

        td.appendChild(box);
        return td;
      }

      function calculateRowsPerPage() {
        const rootStyle = getComputedStyle(document.documentElement);
        const rootFontSize = parseFloat(rootStyle.fontSize);
        const headHeight = parseFloat(rootStyle.getPropertyValue('--table-head-height')) * rootFontSize;
        const available = Math.max(0, els.scoreboard.clientHeight - headHeight - 12);
        const targetRows = 10;
        const maximumRowHeight = 4.65 * rootFontSize;
        const rowSafety = targetRows * 2;
        const fittedRowHeight = Math.min(maximumRowHeight, Math.max(43, (available - rowSafety) / targetRows));
        document.documentElement.style.setProperty('--row-height', `${fittedRowHeight}px`);
        els.scoreboard.classList.toggle('compact-rows', fittedRowHeight < 72);
        state.rowsPerPage = targetRows;
      }

      function renderPage(animate = true) {
        calculateRowsPerPage();
        updateColumnLayout();
        const teamPageCount = Math.max(1, Math.ceil(state.rows.length / state.rowsPerPage));
        const problemPageCount = Math.max(1, Math.ceil(state.problems.length / state.problemsPerPage));
        const pageCount = teamPageCount * problemPageCount;
        state.currentPage = Math.min(state.currentPage, pageCount - 1);
        const teamPage = state.currentPage % teamPageCount;
        const problemPage = Math.floor(state.currentPage / teamPageCount);
        const rowStart = teamPage * state.rowsPerPage;
        const problemStart = problemPage * state.problemsPerPage;
        const visibleRows = state.rows.slice(rowStart, rowStart + state.rowsPerPage);
        const visibleProblemIndices = state.problems
          .map((_, index) => index)
          .slice(problemStart, problemStart + state.problemsPerPage);
        buildHeader(visibleProblemIndices);
        els.standingsBody.replaceChildren();
        els.emptyState.classList.toggle('visible', state.rows.length === 0);

        visibleRows.forEach((row, index) => {
          const tr = document.createElement('tr');
          if (row.party.ghost === true) tr.classList.add('ghost-row');
          tr.style.setProperty('--row-index', String(index));
          if (animate) tr.classList.add('is-new');
          const absoluteRowIndex = rowStart + index;
          if (absoluteRowIndex > 0 && state.scoring.group(state.rows[absoluteRowIndex - 1]) !== state.scoring.group(row)) {
            tr.classList.add('score-group-start');
          }
          const key = participantKey(row);
          const recentProblems = state.recentSolves.get(key);
          const now = Date.now();
          const recentProblemLabels = recentProblems
            ? [...recentProblems.entries()]
                .filter(([, expiresAt]) => expiresAt > now)
                .map(([problemIndex]) => state.problems[problemIndex]?.index || String(problemIndex + 1))
            : [];
          const hasRecentSolve = recentProblemLabels.length > 0;
          if (hasRecentSolve) tr.classList.add('recent-solve');

          tr.append(
            makeRankCell(row),
            makeTeamCell(row, recentProblemLabels),
            ...state.scoring.columns.map(column => makeScoreCell(row[column.field] ?? 0, column.className, column.format))
          );
          visibleProblemIndices.forEach((problemIndex) => tr.appendChild(makeProblemCell(
            row.problemResults?.[problemIndex],
            (recentProblems?.get(problemIndex) || 0) > now,
            state.problems[problemIndex]
          )));
          els.standingsBody.appendChild(tr);
        });

        els.pageDots.replaceChildren();
        if (problemPageCount > 1 || pageCount > 8) {
          const label = document.createElement('span');
          label.className = 'page-label';
          const firstProblem = state.problems[visibleProblemIndices[0]]?.index;
          const lastVisibleProblemIndex = visibleProblemIndices[visibleProblemIndices.length - 1];
          const lastProblem = state.problems[lastVisibleProblemIndex]?.index;
          const problemLabel = firstProblem
            ? `Problems ${firstProblem}${lastProblem !== firstProblem ? `–${lastProblem}` : ''}`
            : 'Scoreboard';
          const rowEnd = Math.min(rowStart + state.rowsPerPage, state.rows.length);
          const unit = state.scoring.id === 'IOI' ? 'Participants' : 'Teams';
          const teamLabel = state.rows.length ? `${unit} ${rowStart + 1}–${rowEnd} of ${state.rows.length}` : `No ${unit.toLowerCase()}`;
          label.textContent = `${problemLabel} · ${teamLabel}`;
          els.pageDots.appendChild(label);
        } else if (pageCount > 1) {
          for (let index = 0; index < pageCount; index += 1) {
            const dot = document.createElement('span');
            dot.className = `page-dot ${index === state.currentPage ? 'active' : ''}`.trim();
            els.pageDots.appendChild(dot);
          }
        }
        restartPageTimer(pageCount);
      }

      function restartPageTimer(pageCount = Math.max(1, Math.ceil(state.rows.length / state.rowsPerPage))) {
        if (pageCount <= 1) {
          clearTimeout(state.pageTimer);
          state.pageTimer = null;
          return;
        }
        if (state.pageTimer !== null) return;
        const delay = state.currentPage === 0 ? config.firstPageMs : config.pageMs;
        state.pageTimer = setTimeout(() => {
          state.pageTimer = null;
          state.currentPage = (state.currentPage + 1) % pageCount;
          renderPage(true);
        }, delay);
      }

      function updateSummary() {
        const contest = state.contest;
        const label = `${state.scoring.id} Live Scoreboard`;
        els.scoreboardLabel.textContent = label;
        document.title = contest?.name ? `${contest.name} | ${label}` : label;
        els.contestName.textContent = contest?.name || label;
        els.contestIdMeta.textContent = state.demo
          ? 'Demo contest'
          : `${state.sourceLabel} standings`;
        const unit = state.scoring.id === 'IOI' ? 'participant' : 'team';
        els.teamCount.textContent = `${state.rows.length.toLocaleString()} ${unit}${state.rows.length === 1 ? '' : 's'}`;
        els.provider.innerHTML = `Data from ${state.sourceLabel} · refreshes every <span id="refreshSeconds">${config.refreshMs / 1000}</span>s`;
        els.demoBadge.classList.toggle('visible', state.demo);
        setPhase(contest?.phase);
        updateClock();
      }

      function visibleParticipant(row) {
        if (state.source === 'codeforces' && row.party.ghost === true) {
          return state.showGhosts && !(state.contest?.type === 'IOI' && state.contest.phase !== 'FINISHED');
        }
        return row.party.participantType === 'CONTESTANT'
          || (config.showUnofficial && row.party.participantType === 'OUT_OF_COMPETITION');
      }

      function visibleStandingsRows(rows) {
        // Original ghosts must not push local teams beyond the default row cap.
        const limit = state.source === 'codeforces' && state.showGhosts && !params.has('count')
          ? rows.length : config.count;
        return rows.filter(visibleParticipant).slice(0, limit);
      }

      function applyData(data, { demo = false } = {}) {
        const result = data.result || data;
        const scoring = ScoreboardScoring.forContest(result.contest);
        const isInitialRender = state.rows.length === 0;
        const previousRows = new Map(state.rows.map((row) => [participantKey(row), row]));
        const now = Date.now();
        for (const [key, recentProblems] of state.recentSolves) {
          for (const [problemIndex, expiresAt] of recentProblems) {
            if (expiresAt <= now) recentProblems.delete(problemIndex);
          }
          if (recentProblems.size === 0) state.recentSolves.delete(key);
        }
        state.contest = result.contest;
        state.scoring = scoring;
        state.receivedAt = Number.isFinite(result.contest?.observedAtSeconds)
          ? result.contest.observedAtSeconds * 1000 : Date.now();
        state.problems = result.problems || [];
        const nextRows = visibleStandingsRows(result.rows || []);
        if (isInitialRender) {
          state.recentSolves.clear();
        } else {
          nextRows.forEach((row) => {
            const key = participantKey(row);
            const newlySolved = newlySolvedProblemIndices(previousRows.get(key), row);
            if (newlySolved.length) {
              const recentProblems = state.recentSolves.get(key) || new Map();
              newlySolved.forEach((problemIndex) => {
                recentProblems.set(problemIndex, now + config.recentSolveMs);
              });
              state.recentSolves.set(key, recentProblems);
            }
          });
        }
        state.rows = nextRows;
        state.demo = demo;
        updateSummary();
        renderPage(isInitialRender);
      }

      async function fetchStandings({ silent = false } = {}) {
        if (!state.standingsUrl || state.loading) return;
        state.loading = true;
        if (!silent) setSync('loading', 'Updating standings…');
        els.refreshButton.disabled = true;

        const controller = new AbortController();
        state.controller = controller;
        const requestId = ++state.requestId;
        const timeout = setTimeout(() => controller.abort(), 30000);
        try {
          const proxyUrl = new URL('api/standings', location.href);
          const requestParams = { source: state.source, url: state.standingsUrl };
          if (state.source === 'codeforces') {
            const target = codeforcesTarget(state.standingsUrl, state.groupCode);
            requestParams.contestId = target.id;
            requestParams.groupCode = target.group;
            requestParams.ghosts = String(state.showGhosts);
            delete requestParams.url;
          }
          proxyUrl.search = new URLSearchParams(requestParams);
          const response = await fetch(proxyUrl, { signal: controller.signal, cache: 'no-store' });
          const data = await response.json().catch(() => null);
          if (requestId !== state.requestId) return;
          if (!response.ok || data?.status !== 'OK') {
            throw new Error(data?.comment || `${state.sourceLabel} returned HTTP ${response.status}`);
          }
          applyData(data);
          state.lastUpdated = new Date();
          localStorage.setItem('icpc-source', state.source);
          localStorage.setItem(`icpc-${state.source}-url`, state.standingsUrl);
          if (state.source === 'codeforces') {
            localStorage.setItem('icpc-codeforces-group', state.groupCode);
            localStorage.setItem('icpc-codeforces-ghosts', String(state.showGhosts));
          }
          try { localStorage.setItem(standingsCacheKey(), JSON.stringify(data)); } catch (_) {}
          setSync('', `Updated ${formatClock(state.lastUpdated)}`);
          els.dialogError.textContent = '';
          if (els.setupDialog.open) els.setupDialog.close();
        } catch (error) {
          if (requestId !== state.requestId) return;
          const message = error.name === 'AbortError' ? `${state.sourceLabel} did not respond in time` : error.message;
          const cached = localStorage.getItem(standingsCacheKey());
          if (!state.rows.length && cached) {
            try {
              applyData(JSON.parse(cached));
              setSync('error', 'Offline · showing last saved standings');
            } catch (_) { setSync('error', message); }
          } else {
            setSync('error', state.rows.length ? `${message} · will retry` : message);
          }
          if (els.setupDialog.open) els.dialogError.textContent = message;
        } finally {
          clearTimeout(timeout);
          if (requestId === state.requestId) {
            state.loading = false;
            state.controller = null;
            els.refreshButton.disabled = false;
          }
        }
      }

      function standingsCacheKey() {
        return `icpc-standings-${state.source}-${state.standingsUrl || 'configured'}${state.source === 'codeforces' ? `-group-${state.groupCode}-ghosts-${state.showGhosts}-replay-v4` : ''}`;
      }

      function cancelRequest() {
        state.requestId += 1;
        state.controller?.abort();
        state.controller = null;
        state.loading = false;
        els.refreshButton.disabled = false;
      }

      function scheduleRefresh() {
        clearInterval(state.refreshTimer);
        state.refreshTimer = setInterval(() => {
          if (!els.setupDialog.open && !state.demo) fetchStandings({ silent: false });
        }, config.refreshMs);
      }

      function useContest(value) {
        const source = els.sourceSelect.value;
        const ioiMaximum = source === 'codeforces' ? Number(els.ioiMaximumInput.value) : state.ioiMaximum;
        if (!Number.isFinite(ioiMaximum) || ioiMaximum <= 0) {
          els.dialogError.textContent = 'IOI maximum points must be a positive number.';
          return;
        }
        let urlValue, groupCode = '';
        if (source === 'codeforces') {
          try {
            const target = codeforcesTarget(value, els.groupInput.value);
            urlValue = target.url;
            groupCode = target.group;
          } catch (error) {
            els.dialogError.textContent = error.message;
            return;
          }
        } else {
          let parsedUrl;
          try { parsedUrl = new URL(value.trim()); } catch (_) {}
          if (!parsedUrl || !/^https?:$/.test(parsedUrl.protocol) || parsedUrl.username || parsedUrl.password) {
            els.dialogError.textContent = 'Enter a public scoreboard URL.';
            return;
          }
          urlValue = parsedUrl.href;
        }
        let aliases;
        try {
          aliases = JSON.parse(els.aliasesInput.value || '{}');
          if (!aliases || typeof aliases !== 'object' || Array.isArray(aliases) || Object.values(aliases).some((value) => typeof value !== 'string')) throw new Error();
        } catch (_) {
          els.dialogError.textContent = 'University names must be a JSON object mapping full names to short names.';
          return;
        }
        cancelRequest();
        state.source = source;
        state.sourceLabel = sourceLabels[source];
        state.standingsUrl = urlValue;
        state.groupCode = groupCode;
        state.ioiMaximum = ioiMaximum;
        localStorage.setItem('icpc-ioi-maximum', String(ioiMaximum));
        state.showGhosts = source === 'codeforces' && els.ghostsInput.checked;
        if (source === 'codeforces') {
          localStorage.setItem('icpc-codeforces-group', groupCode);
          localStorage.setItem('icpc-codeforces-ghosts', String(state.showGhosts));
        }
        state.universityAliases = { ...serverConfig.universityAliases, ...aliases };
        // Store only overrides so subsequent server updates reach this browser.
        const aliasOverrides = Object.fromEntries(Object.entries(aliases).filter(
          ([name, alias]) => alias !== serverConfig.universityAliases?.[name]
        ));
        localStorage.setItem('icpc-university-aliases', JSON.stringify(aliasOverrides));
        localStorage.setItem('icpc-source', source);
        if (state.standingsUrl) localStorage.setItem(`icpc-${source}-url`, state.standingsUrl);
        state.rows = [];
        state.problems = [];
        state.contest = null;
        state.scoring = ScoreboardScoring.forContest();
        state.recentSolves.clear();
        state.demo = false;
        clearTimeout(state.pageTimer);
        state.pageTimer = null;
        state.currentPage = 0;
        const url = new URL(location.href);
        for (const key of ['source', 'contest', 'group', 'auth', 'url', 'ghosts', 'ioiMaxPoints']) url.searchParams.delete(key);
        url.searchParams.set('source', source);
        if (source === 'codeforces') url.searchParams.set('ghosts', String(state.showGhosts));
        if (source === 'codeforces') url.searchParams.set('ioiMaxPoints', String(state.ioiMaximum));
        if (state.standingsUrl) url.searchParams.set('url', state.standingsUrl);
        history.replaceState({}, '', url);
        updateSummary();
        renderPage(true);
        els.contestName.textContent = `Loading ${state.sourceLabel} standings…`;
        fetchStandings();
        scheduleRefresh();
      }

      function showSetup() {
        cancelRequest();
        els.sourceSelect.value = state.source;
        els.contestInput.value = contestDisplayValue();
        els.groupInput.value = state.groupCode;
        els.ghostsInput.checked = state.showGhosts;
        els.ioiMaximumInput.value = state.ioiMaximum;
        els.aliasesInput.value = JSON.stringify(state.universityAliases, null, 2);
        updateSourceFields();
        els.dialogError.textContent = '';
        if (!els.setupDialog.open) els.setupDialog.showModal();
        setTimeout(() => els.contestInput.focus(), 50);
      }

      function updateSourceFields() {
        const codeforces = els.sourceSelect.value === 'codeforces';
        els.setupDialog.querySelector('label[for="contestInput"]').textContent = codeforces ? 'Contest ID or URL' : 'Scoreboard URL';
        els.contestInput.placeholder = codeforces ? 'https://codeforces.com/group/.../contest/...' : 'https://example.org/public';
        $('#codeforcesOptions').hidden = !codeforces;
        els.ioiMaximumInput.disabled = !codeforces;
      }

      function demoData() {
        const names = [
          ['Binary Beasts', ['aurora', 'bitshift', 'kilobyte']], ['Stack Underflow', ['mina', 'theo', 'lin']],
          ['Segmentation Fault', ['nova', 'dijkstra', 'turing']], ['Three Pointer Tango', ['pixel', 'vector', 'lambda']],
          ['Runtime Terrors', ['echo', 'quark', 'flux']], ['The Greedy Bunch', ['ivy', 'nash', 'ramanujan']],
          ['Works on Sample', ['cipher', 'atlas', 'ember']], ['DP Enjoyers', ['sage', 'orbit', 'zen']],
          ['Coffee to Code', ['byte', 'kernel', 'sudo']], ['Wrong Answer 42', ['lumen', 'cosmo', 'rune']],
          ['Overfit to Samples', ['delta', 'axiom', 'matrix']], ['Return of the Recursion', ['ada', 'grace', 'edsger']],
          ['Heap Happens', ['cache', 'malloc', 'pointer']], ['The Last Submit', ['alpha', 'beta', 'gamma']]
        ];
        const problems = 'ABCDEFGHIJK'.split('').map((index, i) => ({ index, name: `Problem ${index}`, points: 1, i }));
        const solvedCounts = [9, 8, 8, 7, 7, 6, 6, 6, 5, 5, 4, 4, 3, 2];
        const rows = names.map(([teamName, handles], teamIndex) => {
          const solved = solvedCounts[teamIndex];
          const problemResults = problems.map((_, problemIndex) => {
            if (problemIndex < solved) {
              return { points: 1, rejectedAttemptCount: (teamIndex + problemIndex * 2) % 4, bestSubmissionTimeSeconds: (18 + teamIndex * 9 + problemIndex * 24) * 60 };
            }
            const failed = (teamIndex * 3 + problemIndex) % 5 === 0;
            return { points: 0, rejectedAttemptCount: failed ? ((teamIndex + problemIndex) % 3) + 1 : 0 };
          });
          return {
            rank: teamIndex + 1,
            points: solved,
            penalty: solved * 71 + teamIndex * 23,
            party: { participantType: 'CONTESTANT', teamId: teamIndex + 1, teamName, members: handles.map((handle) => ({ handle })) },
            problemResults
          };
        });
        return {
          contest: { id: 2045, name: 'Northern Collegiate Programming Championship 2026', phase: 'CODING', durationSeconds: 18000, startTimeSeconds: Math.floor(Date.now() / 1000) - 2 * 3600 - 14 * 60 },
          problems, rows
        };
      }

      els.setupForm.addEventListener('submit', (event) => {
        event.preventDefault();
        useContest(els.contestInput.value);
      });
      els.sourceSelect.addEventListener('change', () => {
        const source = els.sourceSelect.value;
        const defaults = sourceDefaults[source] || {};
        if (source === state.source) {
          els.contestInput.value = contestDisplayValue();
        } else {
          els.contestInput.value = localStorage.getItem(`icpc-${source}-url`) || defaults.standingsUrl || '';
        }
        els.groupInput.value = source === state.source ? state.groupCode
          : source === 'codeforces' ? savedCodeforcesGroup(defaults) : '';
        els.ghostsInput.checked = source === state.source ? state.showGhosts
          : source === 'codeforces' && localStorage.getItem('icpc-codeforces-ghosts') === 'true';
        els.dialogError.textContent = '';
        updateSourceFields();
      });
      els.previewButton.addEventListener('click', () => {
        cancelRequest();
        applyData(demoData(), { demo: true });
        els.setupDialog.close();
        setSync('', 'Preview data · choose a contest when ready');
      });
      els.settingsButton.addEventListener('click', showSetup);
      els.refreshButton.addEventListener('click', () => state.demo ? applyData(demoData(), { demo: true }) : fetchStandings());
      els.fullscreenButton.addEventListener('click', async () => {
        try {
          if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
          else await document.exitFullscreen();
        } catch (_) {}
      });
      window.addEventListener('resize', () => renderPage(false));
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden && !els.setupDialog.open && !state.demo && state.standingsUrl) fetchStandings();
      });

      state.clockTimer = setInterval(updateClock, 1000);
      updateClock();
      if (state.standingsUrl) {
        els.contestName.textContent = `Loading ${state.sourceLabel} standings…`;
        fetchStandings();
        scheduleRefresh();
      } else {
        updateSummary();
        renderPage(false);
        setSync('', 'Choose a contest');
        showSetup();
      }
    })();

