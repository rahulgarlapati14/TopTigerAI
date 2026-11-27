import { createTiger } from './tiger.js';

const onboarding = ['welcome', 'about', 'measurements', 'goals', 'experience', 'fighter', 'identity'];
const labels = ['About you', 'Weight and height', 'Boxing goals', 'Experience', 'Choose your tiger', 'Fighter card'];
const otherScreens = { signup: 'New member sign-up', gym: 'Your corner', round: 'Training', training: 'Video review', calibrate: 'Fuel', 'in-person': 'Gym check-in', store: 'Top Tiger Team Boxing' };
const mainTabs = [...document.querySelectorAll('#gym-nav button')];
const gymNav = document.querySelector('#gym-nav');
const stage = document.querySelector('#tiger-stage');
const canvas = document.querySelector('#tiger');
const status = document.querySelector('#tiger-status');
const ringName = document.querySelector('#ring-name');
const card = document.querySelector('#fighter-card');
const signup = document.querySelector('#signup-form');
const signupEmail = document.querySelector('#signup-email');
const signupEmailConfirm = document.querySelector('#signup-email-confirm');
const signupPassword = document.querySelector('#signup-password');
const signupPasswordConfirm = document.querySelector('#signup-password-confirm');
const goalsForm = document.querySelector('#goals-form');
const goalsError = document.querySelector('#goals-error');
const experienceForm = document.querySelector('#experience-form');
const goalFocus = {
  basics: 'Stance and footwork',
  technique: 'Form review and targeted drills',
  fitness: 'Build consistency with timed rounds',
  weight: 'Build a regular training routine',
  confidence: 'Build a repeatable gym routine',
  competition: 'Discuss competition readiness with a coach',
};
const programNames = {
  beginner: 'Bengal Tiger · First Bell',
  rookie: 'Sumatran Tiger · Boxing Foundations',
  developing: 'Indochinese Tiger · Skill Builder',
  skilled: 'Amur Tiger · Performance Review',
};
const finishes = {
  amber: [1, 0.54, 0.18],
  ivory: [0.86, 0.86, 0.77],
  copper: [0.83, 0.39, 0.27],
};

let current = 'welcome';
let finish = document.querySelector('input[name="finish"]:checked').value;
let tigerType = '';
let tiger;
let loading;
let rounds = 0;
const dailyRounds = new Map();
const roundsPerLevel = 3;
const roundLength = 120000;
let remaining = roundLength;
let deadline;
let clockInterval;
const clock = document.querySelector('#round-clock');
const roundStatus = document.querySelector('#round-status');
const roundToggle = document.querySelector('#round-toggle');

function showScreen(id) {
  if (current === 'signup' && id !== 'signup') {
    signup.reset();
    signupEmailConfirm.setCustomValidity('');
    signupPasswordConfirm.setCustomValidity('');
  }
  if (current === 'round' && deadline) pauseRound();
  current = id;
  const stepNumber = onboarding.indexOf(id);
  for (const screen of [...onboarding, ...Object.keys(otherScreens)]) {
    document.getElementById(screen).hidden = screen !== id;
  }
  document.querySelector('#boxing-header').hidden = id === 'welcome';
  document.querySelector('#step-label').textContent = stepNumber > 0
    ? stepNumber + ' of ' + labels.length + ' · ' + labels[stepNumber - 1]
    : otherScreens[id] ?? '';
  document.querySelector('.steps').hidden = stepNumber < 1;
  document.querySelectorAll('.steps i').forEach((step, index) => {
    step.classList.toggle('active', index < stepNumber);
  });
  const tabIndex = mainTabs.findIndex(tab => tab.dataset.next === (id === 'round' ? 'gym' : id));
  gymNav.hidden = tabIndex < 0;
  if (tabIndex >= 0) gymNav.style.setProperty('--active-tab', tabIndex);
  document.querySelector('.station').classList.toggle('with-nav', !gymNav.hidden);
  for (const [index, tab] of mainTabs.entries()) {
    if (index === tabIndex) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  }

  const slot = document.querySelector('#' + id + ' .stage-slot');
  stage.hidden = !slot;
  if (slot) {
    slot.append(stage);
    loading ??= createTiger(canvas).then(model => {
      tiger = model;
      canvas.hidden = false;
      status.hidden = true;
      paintTiger();
    }).catch(() => {
      status.textContent = 'The 3D preview is unavailable.';
    });
    paintTiger();
  }

  const name = ringName.value.trim();
  card.textContent = name ? name + ' · Boxing' : 'Boxing';
  if (id === 'gym') {
    updateGym(name);
    updateStartingPlan();
  }
  if (id === 'calibrate') updateFuel();
  if (id === 'in-person') updateRoster();
  window.scrollTo(0, 0);
  document.getElementById(id + '-title').focus({ preventScroll: true });
}

function updateStartingPlan() {
  const experience = new FormData(experienceForm).get('experience');
  const months = Number(document.querySelector('#training-months').value);
  const goals = new FormData(goalsForm).getAll('goal');
  const weightGoal = goals.includes('weight');
  const boxingTrack = programNames[experience];
  document.querySelector('#plan-title').textContent = weightGoal ? 'Malayan Tiger · Boxing Conditioning' : boxingTrack;
  const firstStep = months === 0
    ? 'Start with a short introductory round.'
    : months < 6
      ? 'Start by repeating one familiar drill across a few sessions.'
      : 'Start by reviewing a recent round and choosing one thing to improve.';
  document.querySelector('#plan-start').textContent = weightGoal
    ? 'Build a consistent boxing and conditioning routine at your current level.'
    : firstStep;
  const companionTrack = document.querySelector('#plan-boxing-track');
  companionTrack.hidden = !weightGoal;
  companionTrack.textContent = weightGoal ? 'Boxing skills track · ' + boxingTrack + '. ' + firstStep : '';
  const focus = document.querySelector('#plan-focus');
  focus.replaceChildren();
  for (const goal of goals) {
    const item = document.createElement('li');
    item.textContent = goalFocus[goal];
    focus.append(item);
  }
}

function boxingLevel() {
  return Math.floor(rounds / roundsPerLevel) + 1;
}

function dayKey(date = new Date()) {
  return date.toDateString();
}

function renderWeek(container) {
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - (today.getDay() + 6) % 7);
  container.replaceChildren();
  for (let day = 0; day < 7; day += 1) {
    const date = new Date(monday);
    date.setDate(monday.getDate() + day);
    const cell = document.createElement('span');
    cell.textContent = date.toLocaleDateString('en-US', { weekday: 'narrow' });
    const number = document.createElement('strong');
    number.textContent = date.getDate();
    cell.append(number);
    if (dayKey(date) === dayKey(today)) cell.setAttribute('aria-current', 'date');
    container.append(cell);
  }
}

function updateGym(name) {
  const level = boxingLevel();
  const completed = rounds % roundsPerLevel;
  document.querySelector('#gym-title').textContent = name ? 'Welcome back, ' + name + '!' : 'Welcome back!';
  document.querySelector('#gym-level').textContent = 'Level ' + level + (level === 1 ? ' · Rookie' : '');
  document.querySelector('#gym-progress-label').textContent = completed + ' of ' + roundsPerLevel + ' rounds to level ' + (level + 1);
  document.querySelector('#gym-progress').value = completed;
  const today = dailyRounds.get(dayKey()) ?? 0;
  document.querySelector('#gym-today').textContent = today + (today === 1 ? ' round done' : ' rounds done');
  renderWeek(document.querySelector('#gym-week'));
}

function updateClock() {
  if (deadline) remaining = Math.max(0, deadline - Date.now());
  const seconds = Math.ceil(remaining / 1000);
  clock.textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
  if (remaining === 0 && deadline) {
    clearInterval(clockInterval);
    deadline = undefined;
    rounds += 1;
    const today = dayKey();
    dailyRounds.set(today, (dailyRounds.get(today) ?? 0) + 1);
    roundStatus.textContent = rounds % roundsPerLevel === 0 ? 'Round complete. Level up!' : 'Round complete. One round earned.';
    roundToggle.textContent = 'Start another round';
  }
}

function pauseRound() {
  updateClock();
  if (!deadline) return;
  clearInterval(clockInterval);
  deadline = undefined;
  roundStatus.textContent = 'Round paused.';
  roundToggle.textContent = 'Resume round';
}

roundToggle.addEventListener('click', () => {
  if (deadline) {
    pauseRound();
    return;
  }
  if (remaining === 0) remaining = roundLength;
  deadline = Date.now() + remaining;
  roundStatus.textContent = '';
  roundToggle.textContent = 'Pause round';
  updateClock();
  clockInterval = setInterval(updateClock, 200);
});

const meals = [];
let weighIn;
const weighForm = document.querySelector('#weigh-form');
const mealForm = document.querySelector('#meal-form');

function updateFuel() {
  renderWeek(document.querySelector('#fuel-week'));
  const weight = document.querySelector('#weight');
  const currentWeight = weighIn ?? (weight.value ? weight.value + ' ' + weight.nextElementSibling.value : '');
  document.querySelector('#weigh-summary').textContent = currentWeight ? 'Weight · ' + currentWeight + ' · Weigh in' : 'Weigh in';
  const todaysMeals = meals.filter(meal => meal.date === dayKey());
  for (const nutrient of ['kcal', 'protein', 'carbs', 'fat']) {
    const total = todaysMeals.reduce((sum, meal) => sum + meal[nutrient], 0);
    document.querySelector('#fuel-' + nutrient).textContent = total.toLocaleString() + (nutrient === 'kcal' ? '' : ' g');
  }
  const list = document.querySelector('#meal-list');
  list.replaceChildren();
  for (const meal of todaysMeals) {
    const row = document.createElement('li');
    row.textContent = meal.name + ' · ' + meal.kcal + ' kcal';
    list.append(row);
  }
  list.hidden = !todaysMeals.length;
  document.querySelector('#meal-empty').hidden = Boolean(todaysMeals.length);
  document.querySelector('#meal-count').textContent = todaysMeals.length + ' today';
}

weighForm.addEventListener('submit', event => {
  event.preventDefault();
  weighIn = document.querySelector('#weigh-value').value + ' ' + document.querySelector('#weigh-unit').value;
  weighForm.closest('details').open = false;
  updateFuel();
});

mealForm.addEventListener('submit', event => {
  event.preventDefault();
  const data = new FormData(mealForm);
  const name = data.get('meal').trim();
  if (!name) return;
  meals.push({
    name, date: dayKey(), kcal: Number(data.get('kcal')),
    protein: Number(data.get('protein')), carbs: Number(data.get('carbs')), fat: Number(data.get('fat')),
  });
  mealForm.reset();
  mealForm.closest('details').open = false;
  updateFuel();
});

let checkedIn = false;
const checkInButton = document.querySelector('#check-in');
function updateRoster() {
  const roster = document.querySelector('#gym-roster');
  roster.replaceChildren();
  if (checkedIn) {
    const row = document.createElement('li');
    const name = ringName.value.trim();
    row.textContent = (name ? name + ' (you)' : 'Your tiger') + ' · Level ' + boxingLevel();
    roster.append(row);
  }
  roster.hidden = !checkedIn;
  document.querySelector('#roster-empty').hidden = checkedIn;
  document.querySelector('#check-in-status').textContent = checkedIn ? 'Checked in' : 'Checked out';
  checkInButton.textContent = checkedIn ? 'Check out' : 'Check in';
}
checkInButton.addEventListener('click', () => {
  checkedIn = !checkedIn;
  updateRoster();
});

function paintTiger() {
  if (!tiger || stage.hidden) return;
  canvas.setAttribute('aria-label', [finish, tigerType, '3D tiger model'].filter(Boolean).join(' '));
  tiger.draw(finishes[finish], tigerType === 'female' ? 0.86 : 1);
}

document.querySelectorAll('[data-next]').forEach(button => {
  button.addEventListener('click', () => {
    if (button.dataset.next !== current) showScreen(button.dataset.next);
  });
});
document.querySelector('#back').addEventListener('click', () => {
  const previous = { round: 'gym', training: 'gym', calibrate: 'gym', 'in-person': 'gym', store: 'gym', gym: 'identity', signup: 'welcome' };
  showScreen(previous[current] ?? onboarding[onboarding.indexOf(current) - 1]);
});
signup.addEventListener('input', () => {
  signupEmailConfirm.setCustomValidity('');
  signupPasswordConfirm.setCustomValidity('');
});
signup.addEventListener('submit', event => {
  event.preventDefault();
  signupEmailConfirm.setCustomValidity(signupEmail.value === signupEmailConfirm.value ? '' : 'Email addresses must match.');
  signupPasswordConfirm.setCustomValidity(signupPassword.value === signupPasswordConfirm.value ? '' : 'Passwords must match.');
  if (signup.reportValidity()) showScreen('about');
});
document.querySelector('#about-form').addEventListener('submit', event => {
  event.preventDefault();
  const sex = document.querySelector('input[name="sex"]:checked').value;
  tigerType = sex === 'undisclosed' ? '' : sex;
  document.querySelector('#tiger-type').textContent = tigerType ? tigerType + ' tiger · Boxing' : 'Boxing';
  showScreen('measurements');
});
document.querySelector('#measurements-form').addEventListener('submit', event => {
  event.preventDefault();
  showScreen('goals');
});
goalsForm.addEventListener('change', () => { goalsError.hidden = true; });
goalsForm.addEventListener('submit', event => {
  event.preventDefault();
  if (!goalsForm.querySelector('input:checked')) {
    goalsError.hidden = false;
    goalsForm.querySelector('input').focus();
    return;
  }
  showScreen('experience');
});
experienceForm.addEventListener('submit', event => {
  event.preventDefault();
  showScreen('fighter');
});
document.querySelector('#ring-form').addEventListener('submit', event => {
  event.preventDefault();
  showScreen('gym');
});
document.querySelector('.finishes').addEventListener('change', event => {
  finish = event.target.value;
  paintTiger();
});
new ResizeObserver(paintTiger).observe(canvas);
