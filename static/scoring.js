// Scoring-specific presentation; fetching, pagination and DOM rendering are shared.
const ScoreboardScoring = (() => {
  'use strict';

  function formatScore(value) {
    const score = Number(value);
    return Number.isFinite(score) ? score.toLocaleString('en-US', { maximumFractionDigits: 8 }) : '0';
  }

  function maximum(problem, fallback = 100) {
    const points = Number(problem?.points);
    return Number.isFinite(points) && points > 0 ? points : fallback;
  }

  function pending(result) {
    return result?.frozen === true;
  }

  const modes = {
    ICPC: {
      id: 'ICPC', participantLabel: 'Team', recentLabel: 'Solved',
      columns: [
        { className: 'solved-col', label: 'Solved', sub: 'Total', field: 'points', format: value => String(Math.round(Number(value) || 0)) },
        { className: 'penalty-col', label: 'Penalty', sub: 'Minutes', field: 'penalty', format: formatScore }
      ],
      improved: (previous, current) => Number(current?.points || 0) > 0 && Number(previous?.points || 0) <= 0,
      group: row => Number(row.points || 0),
      problem(result) {
        const solved = Number(result?.points || 0) > 0;
        const attempts = Number(result?.rejectedAttemptCount || 0);
        return {
          status: solved ? 'solved' : pending(result) ? 'frozen' : attempts ? 'failed' : 'empty',
          text: solved ? (attempts ? `+${attempts}` : '+')
            : pending(result) ? (result.pendingAttemptCount ? `?${result.pendingAttemptCount}` : '?')
              : attempts ? `\u2212${attempts}` : '\u00b7',
          time: solved ? result.bestSubmissionTimeSeconds : undefined,
          first: solved && result?.firstToSolve === true
        };
      }
    },
    IOI: {
      id: 'IOI', participantLabel: 'Participant', recentLabel: 'Improved',
      columns: [{ className: 'solved-col', label: 'Score', sub: 'Total', field: 'points', format: formatScore }],
      improved: (previous, current) => Number(current?.points || 0) > Number(previous?.points || 0),
      group: () => null,
      problem(result, problem, fallbackMaximum = 100) {
        const score = Number(result?.points || 0);
        const full = score >= maximum(problem, fallbackMaximum);
        const attempted = score > 0 || Number(result?.rejectedAttemptCount || 0) > 0
          || Number.isFinite(result?.bestSubmissionTimeSeconds);
        return {
          status: score > 0 ? (full ? 'solved' : 'partial')
            : pending(result) ? 'frozen' : attempted ? 'failed' : 'empty',
          text: score > 0 ? formatScore(score) : pending(result) ? '?' : attempted ? '0' : '\u00b7',
          time: undefined,
          detail: pending(result) && score > 0 ? '?' : undefined,
          maximum: maximum(problem, fallbackMaximum),
          preliminary: result?.type === 'PRELIMINARY',
          first: false
        };
      }
    }
  };

  function forContest(contest) {
    const type = contest?.type || 'ICPC';
    if (!modes[type]) throw new Error(`Unsupported scoring system: ${type}. Choose an ICPC or IOI contest.`);
    return modes[type];
  }

  return { forContest, maximum, formatScore };
})();
