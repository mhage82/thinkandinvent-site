import { db, ref, push } from "./firebase.js";

export async function postResult({ name, score, totalQuestions, totalTimeSeconds, submittedBy }) {
  try {
    await push(ref(db, "scores"), {
      name,
      score,
      totalQuestions,
      totalTimeSeconds,
      submittedBy,
      timestamp: Date.now()
    });
    console.log("Score submitted:", name, score);
  } catch (err) {
    console.error("Error submitting score:", err);
  }
}
