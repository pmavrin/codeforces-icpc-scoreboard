// Run with JavaScriptCore (jsc) from the repository root. These are not browser layout tests.
const html = readFile('index.html');
const script = html.match(/<script>\s*\(\(\) => \{[\s\S]*?<\/script>/)[0]
  .replace(/^<script>/, '').replace(/<\/script>$/, '');
new Function(script);
function assert(value, message) { if (!value) throw new Error(message); }
function helper(name) {
  const start = script.indexOf('      function ' + name + '(');
  assert(start >= 0, 'Missing helper ' + name);
  const end = script.indexOf('\n      function ', start + 1);
  return script.slice(start, end < 0 ? undefined : end);
}
assert(!html.includes('codeforces.com/api/'), 'No direct Codeforces API calls');
assert(!html.includes('id="apiKeyInput"'), 'No API key form');
assert(!html.includes('crypto.subtle'), 'No browser-side signing');
assert(html.includes('pashka-bot'), 'Dedicated access account is visible');
const savedSettings = {};
const savedGroup = new Function('localStorage', helper('savedCodeforcesGroup') + '\nreturn savedCodeforcesGroup;')({ getItem: key => savedSettings[key] || null });
assert(savedGroup({ groupCode: 'DefaultGroup' }) === 'DefaultGroup', 'Default group accompanies default contest');
savedSettings['icpc-codeforces-url'] = '2045';
assert(savedGroup({ groupCode: 'DefaultGroup' }) === '', 'Saved public contest does not inherit default group');
savedSettings['icpc-codeforces-group'] = 'SavedGroup';
assert(savedGroup({ groupCode: 'DefaultGroup' }) === 'SavedGroup', 'Saved group accompanies saved contest');
const target = new Function(helper('codeforcesTarget') + '\nreturn codeforcesTarget;')();
assert(target('2045').id === '2045', 'Public contest ID');
assert(target('https://codeforces.com/group/ABC/contest/727989/standings').group === 'ABC', 'Group from URL');
assert(target('727989', 'ABC').url === 'https://codeforces.com/group/ABC/contest/727989', 'ID and separate group');
for (const [value, group] of [['https://codeforces.com/spectator/ranklist/abc', ''], ['https://evil.example/contest/2045', ''], ['https://codeforces.com/group/ABC/contest/42', 'XYZ']]) {
  let rejected = false;
  try { target(value, group); } catch (_) { rejected = true; }
  assert(rejected, 'Invalid or conflicting contest target rejected');
}

const serverConfig = { universityAliases: { University: 'U', Another: 'A' } };
let saved = '{}';
const localStorage = { getItem: () => saved };
const aliases = new Function('serverConfig', 'localStorage', helper('readSavedAliases') + '\nreturn readSavedAliases;')(serverConfig, localStorage);
assert(aliases().University === 'U', 'Empty local settings retain server aliases');
saved = '{"University":"Local"}';
assert(aliases().University === 'Local' && aliases().Another === 'A', 'Local overrides merge per name');

const state = { contest: { phase: 'CODING', remainingTimeSeconds: 60 }, receivedAt: Date.now(), universityAliases: {} };
const els = { timerLabel: {}, contestTimer: {} };
const clock = new Function('state', 'els', helper('formatDuration') + helper('updateClock') + '\nreturn updateClock;')(state, els);
clock();
assert(els.timerLabel.textContent === 'Time remaining', 'Spectator clock counts down');
assert(/^00:00:(59|60)$|^00:01:00$/.test(els.contestTimer.textContent), 'Countdown starts at one minute');
state.receivedAt -= 120000;
clock();
assert(els.contestTimer.textContent === '00:00:00', 'Expired countdown clamps to zero');
state.contest = { phase: 'FINISHED', timingAvailable: false };
clock();
assert(els.contestTimer.textContent === '--:--:--', 'Unknown contest duration is not invented');
state.contest = { phase: 'CODING', startTimeSeconds: Date.now() / 1000 - 90, durationSeconds: 18000 };
clock();
assert(els.timerLabel.textContent === 'Contest time', 'Other adapters keep elapsed clock');
assert(els.contestTimer.textContent === '00:01:30', 'Elapsed clock is unchanged');

const display = new Function('state', helper('participantName') + helper('participantMembers') + helper('splitStructuredTeamName') + helper('participantDisplay') + '\nreturn participantDisplay;')(state);
const team = display({ party: { teamName: 'MIR', participantType: 'CONTESTANT', members: [{ handle: 'SomethingNew' }, { handle: 'Other' }] } });
assert(team.name === 'MIR' && team.details === 'SomethingNew \u00b7 Other', 'Codeforces team/member display');
const solo = display({ party: { participantType: 'CONTESTANT', members: [{ handle: 'Solo' }] } });
assert(solo.name === 'Solo', 'Individual participants display their handle');
print('Frontend syntax and helper tests passed');
