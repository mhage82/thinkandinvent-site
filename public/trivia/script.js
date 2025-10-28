/* global TRIVIA_QUESTIONS, postResult */

(function(){
    const TOTAL_SECONDS = 5 * 60; // 5 minutes hard cap
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
    const submitNote = $("#submit-note");
    const answerReview = $("#answer-review");
  
    // State
    const questions = TRIVIA_QUESTIONS.slice(0); // clone
    const totalQ = questions.length;
  
    let playerName = "";
    let currentIdx = 0;
    let selected = new Array(totalQ).fill(null); // store selected answer indices
    let score = 0;
  
    let startEpoch = null;   // ms when quiz actually started
    let tickInterval = null; // setInterval ref
    let remaining = TOTAL_SECONDS;
    let submitted = false;
    let submittedBy = "manual"; // or "auto"
  
    // Init totals
    qTotalEl.textContent = totalQ.toString();
  
    function formatMMSS(sec){
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      return `${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
    }
  
    function setTimerVisibility(show){
      if(show){
        globalTimer.classList.remove("hidden");
      } else {
        globalTimer.classList.add("hidden");
      }
    }
  
    function updateCountdownUI(){
      const timeTxt = formatMMSS(remaining);
      countdownEl.textContent = timeTxt;
      globalTimer.textContent = timeTxt;
  
      if(remaining <= 60){
        countdownWrap.classList.add("danger");
        countdownWrap.classList.remove("warning");
      } else if(remaining <= 120){
        countdownWrap.classList.add("warning");
        countdownWrap.classList.remove("danger");
      }
    }
  
    function startGlobalTimer(){
      startEpoch = Date.now();
      remaining = TOTAL_SECONDS;
      setTimerVisibility(true);
      updateCountdownUI();
  
      tickInterval = setInterval(() => {
        if(remaining <= 0){
          clearInterval(tickInterval);
          submittedBy = "auto";
          autoSubmit();
          return;
        }
        remaining -= 1;
        updateCountdownUI();
      }, 1000);
    }
  
    function renderQuestion(idx){
      const q = questions[idx];
      qIdxEl.textContent = (idx+1).toString();
      qText.textContent = q.text;
  
      // Reset answers
      answersEl.innerHTML = "";
      q.choices.forEach((choice, i) => {
        const btn = document.createElement("button");
        btn.className = "answer";
        btn.type = "button";
        btn.textContent = choice;
  
        // If already selected, lock in visually
        if(selected[idx] !== null){
          if(i === selected[idx]){
            btn.classList.add("selected");
          }
        }
  
        btn.addEventListener("click", () => onSelect(idx, i));
        answersEl.appendChild(btn);
      });
  
      // nav buttons
      prevBtn.disabled = (idx === 0);
      nextBtn.disabled = (idx === totalQ-1);
    }
  
    function onSelect(idx, answerIdx){
      // lock answer once clicked (no changes)
      if(selected[idx] !== null) return;
      selected[idx] = answerIdx;
  
      // Visual
      const childBtns = [...answersEl.children];
      childBtns.forEach((btn, i) => {
        if(i === answerIdx) btn.classList.add("selected");
        // disable all clicks after selection
        btn.style.pointerEvents = "none";
        if(i === questions[idx].correctIndex){
          btn.classList.add("correct");
        } else if(i === answerIdx && i !== questions[idx].correctIndex){
          btn.classList.add("wrong");
        }
      });
    }
  
    function calcScore(){
      let s = 0;
      selected.forEach((ans, i) => {
        if(ans === questions[i].correctIndex) s += 1;
      });
      score = s;
      return score;
    }
  
    function next(){
      if(currentIdx < totalQ-1){
        currentIdx += 1;
        renderQuestion(currentIdx);
      }
    }
  
    function prev(){
      if(currentIdx > 0){
        currentIdx -= 1;
        renderQuestion(currentIdx);
      }
    }
  
    async function submitResults(){
      if(submitted) return;
      submitted = true;
  
      // stop timer
      if(tickInterval) clearInterval(tickInterval);
  
      // If user is still on quiz view, switch to result view
      quizScreen.classList.add("hidden");
      resultScreen.classList.remove("hidden");
  
      const elapsedMs = Math.min(TOTAL_SECONDS, Math.round((Date.now() - startEpoch)/1000)) * 1000;
      const elapsedSec = Math.round(elapsedMs / 1000);
  
      const finalScore = calcScore();
  
      // Fill result UI
      resName.textContent = playerName;
      resScore.textContent = String(finalScore);
      resTotal.textContent = String(totalQ);
      resTime.textContent = formatMMSS(elapsedSec);
      submitNote.textContent = submittedBy === "auto"
        ? "⏰ Time expired — your quiz was auto-submitted."
        : "✅ Submitted successfully.";
  
      // Build answer review
      const frag = document.createDocumentFragment();
      questions.forEach((q, i) => {
        const wrapper = document.createElement("div");
        wrapper.style.marginBottom = "10px";
        const qEl = document.createElement("div");
        qEl.textContent = `Q${i+1}. ${q.text}`;
        qEl.style.fontWeight = "600";
        const aEl = document.createElement("div");
        const userAns = selected[i];
        const correct = q.correctIndex;
        aEl.innerHTML = `Your answer: <strong>${userAns !== null ? q.choices[userAns] : "— (no answer)"}</strong><br/>Correct answer: <strong>${q.choices[correct]}</strong>`;
        wrapper.appendChild(qEl);
        wrapper.appendChild(aEl);
        frag.appendChild(wrapper);
      });
      answerReview.innerHTML = "";
      answerReview.appendChild(frag);
  
      // Post to Google Sheet
      postStatus.textContent = "Saving your score…";
      try{
        await postResult({
          name: playerName,
          score: finalScore,
          totalQuestions: totalQ,
          totalTimeSeconds: elapsedSec,
          submittedBy
        });
        postStatus.textContent = "Saved! Thank you for playing.";
        postStatus.classList.remove("muted");
      }catch(err){
        postStatus.textContent = "Unable to save to the server (you’re still done). Please show this screen to the host.";
        console.error(err);
      }
    }
  
    function autoSubmit(){
      // Mark all unanswered as wrong implicitly (selected stays null).
      submitResults();
    }
  
    // Event listeners
    startBtn.addEventListener("click", () => {
      const val = (nameInput.value || "").trim();
      if(!val){
        nameInput.focus();
        nameInput.classList.add("shake");
        setTimeout(()=>nameInput.classList.remove("shake"), 600);
        return;
      }
      playerName = val;
  
      welcomeScreen.classList.add("hidden");
      quizScreen.classList.remove("hidden");
  
      // Kick off timer and first question
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
  
  })();
  