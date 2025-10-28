/* global TRIVIA_QUESTIONS */
import { database, ref, push, set, onValue } from "./firebase.js";

(function () {
  const TOTAL_SECONDS = 5 * 60; // 5 minutes
  const $ = (sel) => document.querySelector(sel);

  // Elements
  const welcomeScreen = $("#welcome-screen");
  const quizScreen = $("#quiz-screen");
  const resultScreen = $("#result-screen");
  const globalTimer = $("#global-timer");

  const nameInput = $("#player-name");
  const startBtn = $("#start-btn");

  const qText = $("#question-text");
  const answersEl = $("#answers");
  const qIdxEl = $("#q-idx");
  const qTotalEl = $("#q-total");
  const countdownEl = $("#time-remaining");
  const countdownWrap = $("#countdown");
  const prevBtn = $("#prev-btn");
  const nextBtn = $("#next-btn");
  const submitBtn = $("#submit-btn");

  const resName = $("#res-name");
  const resScore = $("#res-score");
  const resTotal = $("#res-total");
  const resTime = $("#res-time");
  const postStatus = $("#post-status");
  const leaderboardEl = $("#leaderboard");

  // State
  const questions = TRIVIA_QUESTIONS.slice();
  const totalQ = questions.length;
  let playerName = "";
  let currentIdx = 0;
  let selected = new Array(totalQ).fill(null);
  let score = 0;
  let startEpoch = null;
  let tickInterval = null;
  let remaining = TOTAL_SECONDS;
  let submitted = false;
  let submittedBy = "manual";

  qTotalEl.textContent = totalQ.toString();

  // Utils
  function formatMMSS(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function setTimerVisibility(show) {
    globalTimer.classList.toggle("hidden", !show);
  }

  function updateCountdownUI() {
    const timeTxt = formatMMSS(remaining);
    countdownEl.textContent = timeTxt;
    globalTimer.textContent = timeTxt;
    if (remaining <= 60) {
      countdownWrap.classList.add("danger");
    } else if (remaining <= 120) {
      countdownWrap.classList.add("warning");
    }
  }

  function startGlobalTimer() {
    startEpoch = Date.now();
    remaining = TOTAL_SECONDS;
    setTimerVisibility(true);
    updateCountdownUI();

    tickInterval = setInterval(() => {
      if (remaining <= 0) {
        clearInterval(tickInterval);
        submittedBy = "auto";
        autoSubmit();
        return;
      }
      remaining -= 1;
      updateCountdownUI();
    }, 1000);
  }

  function renderQuestion(idx) {
    const q = questions[idx];
    qIdxEl.textContent = (idx + 1).toString();
    qText.textContent = q.text;
    answersEl.innerHTML = "";

    q.choices.forEach((choice, i) => {
      const btn = document.createElement("button");
      btn.className = "answer";
      btn.textContent = choice;

      if (selected[idx] !== null && i === selected[idx]) {
        btn.classList.add("selected");
      }

      btn.addEventListener("click", () => onSelect(idx, i));
      answersEl.appendChild(btn);
    });

    prevBtn.disabled = idx === 0;
    nextBtn.disabled = idx === totalQ - 1;
  }

  function onSelect(idx, answerIdx) {
    if (selected[idx] !== null) return;
    selected[idx] = answerIdx;

    // Lock answers visually
    const buttons = [...answersEl.children];
    buttons.forEach((btn, i) => {
      if (i === answerIdx) btn.classList.add("selected");
      btn.style.pointerEvents = "none";
    });
  }

  function calcScore() {
    let s = 0;
    selected.forEach((ans, i) => {
      if (ans === questions[i].correctIndex) s += 1;
    });
    score = s;
    return score;
  }

  function next() {
    if (currentIdx < totalQ - 1) {
      currentIdx++;
      renderQuestion(currentIdx);
    }
  }

  function prev() {
    if (currentIdx > 0) {
      currentIdx--;
      renderQuestion(currentIdx);
    }
  }

  async function submitResults() {
    if (submitted) return;
    submitted = true;
    if (tickInterval) clearInterval(tickInterval);

    quizScreen.classList.add("hidden");
    resultScreen.classList.remove("hidden");

    const elapsedSec = Math.min(TOTAL_SECONDS, Math.round((Date.now() - startEpoch) / 1000));
    const finalScore = calcScore();

    resName.textContent = playerName;
    resScore.textContent = String(finalScore);
    resTotal.textContent = String(totalQ);
    resTime.textContent = formatMMSS(elapsedSec);

    postStatus.textContent = "Saving your score...";

    try {
      // Save to Firebase
      const leaderboardRef = ref(database, "scores");
      const newRef = push(leaderboardRef);
      await set(newRef, {
        name: playerName,
        score: finalScore,
        time: elapsedSec,
        submittedAt: Date.now()
      });

      postStatus.textContent = "✅ Score saved successfully!";
      loadLeaderboard(); // refresh live view
    } catch (err) {
      console.error("Firebase write failed:", err);
      postStatus.textContent =
        "⚠️ Unable to save to the server (you’re still done). Please show this screen to the host.";
    }
  }

  function autoSubmit() {
    submittedBy = "auto";
    submitResults();
  }

  // Leaderboard live updates
  function loadLeaderboard() {
    const leaderboardRef = ref(database, "scores");
    onValue(leaderboardRef, (snapshot) => {
      const data = snapshot.val();
      if (!data) return;
      const scores = Object.values(data)
        .sort((a, b) => b.score - a.score || a.time - b.time)
        .slice(0, 3);
      leaderboardEl.innerHTML = `
        <table class="leaderboard-table">
          <tr><th>Rank</th><th>Name</th><th>Score</th><th>Time</th></tr>
          ${scores
            .map(
              (s, i) =>
                `<tr><td>${i + 1}</td><td>${s.name}</td><td>${s.score}</td><td>${s.time}s</td></tr>`
            )
            .join("")}
        </table>
      `;
    });
  }

  // Event listeners
  startBtn.addEventListener("click", () => {
    const val = (nameInput.value || "").trim();
    if (!val) {
      nameInput.focus();
      nameInput.classList.add("shake");
      setTimeout(() => nameInput.classList.remove("shake"), 600);
      return;
    }
    playerName = val;
    welcomeScreen.classList.add("hidden");
    quizScreen.classList.remove("hidden");
    startGlobalTimer();
    renderQuestion(currentIdx);
    updateCountdownUI();
  });

  nextBtn.addEventListener("click", next);
  prevBtn.addEventListener("click", prev);
  submitBtn.addEventListener("click", () => {
    submittedBy = "manual";
    submitResults();
  });

  // Start live leaderboard
  loadLeaderboard();
})();
