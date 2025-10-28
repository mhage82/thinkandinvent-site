// Import the functions you need
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-app.js";
import { getDatabase, ref, set, push, onValue } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-database.js";
import { getAnalytics } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-analytics.js";

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyAiXXAllCaHfQdJDc1tTKPX0fHZUH7HAao",
  authDomain: "lebanese-trivia.firebaseapp.com",
  databaseURL: "https://lebanese-trivia-default-rtdb.firebaseio.com",
  projectId: "lebanese-trivia",
  storageBucket: "lebanese-trivia.firebasestorage.app",
  messagingSenderId: "436910636749",
  appId: "1:436910636749:web:fe18a31cb2bd41232ab384",
  measurementId: "G-EJRQRVZH76"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);
const database = getDatabase(app);

// Export for other scripts
export { database, ref, set, push, onValue };
