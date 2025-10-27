// Replace with your Google Apps Script Web App URL after deployment
const WEB_APP_URL = "YOUR_DEPLOYED_WEB_APP_URL_HERE";

/**
 * Sends result to Google Sheet backend (Apps Script)
 * @param {{name:string, score:number, totalQuestions:number, totalTimeSeconds:number, submittedBy:'auto'|'manual'}} payload
 */
async function postResult(payload){
  const res = await fetch(WEB_APP_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...payload,
      userAgent: navigator.userAgent || ""
    })
  });
  if(!res.ok){
    const text = await res.text();
    throw new Error(`Server responded ${res.status}: ${text}`);
  }
  return res.json().catch(()=> ({}));
}
