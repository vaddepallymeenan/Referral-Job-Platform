"use client";

import React, { useState, useEffect, useRef } from "react";

interface JobMatch {
  job: {
    id: string;
    company: string;
    title: string;
    description: string;
    url: string;
    source: string;
    ats_type: string;
    posted_at: string;
  };
  match_score: number;
  distance: number;
  gaps: {
    missing_skills: string[];
    resume_optimization: string;
  };
  ats_dynamics?: {
    urgency: string;
    status: string;
    days_open: number;
    hiring_signal: string;
  };
}

interface ResumeData {
  user_id: string;
  raw_text: string;
  structured_json: {
    name: string;
    email: string;
    phone: string;
    skills: string[];
    experience: Array<{
      role: string;
      company: string;
      duration: string;
      description: string;
    }>;
    education: Array<{
      degree: string;
      institution: string;
      year: string;
    }>;
    target_roles: string[];
  };
  updated_at: string;
}

interface TrackedApplication {
  id: string;
  job: {
    id: string;
    company: string;
    title: string;
    description: string;
    url: string;
    source: string;
    ats_type: string;
  };
  status: string;
  updated_at: string;
}

interface OutreachData {
  company_summary: string;
  linkedin_note: string;
}

interface CompanySignalData {
  id: string;
  company: string;
  signal_type: string;
  description: string;
  weight_boost: number;
  recorded_at: string;
}

export default function Home() {
  const [email, setEmail] = useState("");
  const [authInputEmail, setAuthInputEmail] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);
  
  const [isUploading, setIsUploading] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const [resume, setResume] = useState<ResumeData | null>(null);
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [selectedMatch, setSelectedMatch] = useState<JobMatch | null>(null);
  const [uploadError, setUploadError] = useState("");
  
  // Tab and view state
  const [activeMainView, setActiveMainView] = useState<"curation" | "kanban">("curation");
  const [activeTab, setActiveTab] = useState<"matching" | "profile" | "preferences" | "tailoring" | "prep">("matching");
  
  // Month 5 Resume Tailoring and Interview Prep State
  const [tailoringData, setTailoringData] = useState<any[]>([]);
  const [tailoringLoading, setTailoringLoading] = useState(false);
  const [prepQuestions, setPrepQuestions] = useState<any[]>([]);
  const [prepLoading, setPrepLoading] = useState(false);

  // Month 6 Billing & Paywall States
  const [subscriptionTier, setSubscriptionTier] = useState("free");
  const [outreachCount, setOutreachCount] = useState(0);
  const [fitScoreCount, setFitScoreCount] = useState(0);

  // Saved Search Preferences State (Month 4 Retention Engine)
  const [isRemotePref, setIsRemotePref] = useState(false);
  const [locationPref, setLocationPref] = useState("Any");
  const [keywordsPref, setKeywordsPref] = useState("");
  const [isSavingPrefs, setIsSavingPrefs] = useState(false);
  const [isSendingDigest, setIsSendingDigest] = useState(false);
  const [companySignals, setCompanySignals] = useState<CompanySignalData[]>([]);
  
  // Real-time Outreach generation state
  const [outreachData, setOutreachData] = useState<OutreachData | null>(null);
  const [outreachLoading, setOutreachLoading] = useState(false);
  
  // Kanban applications list state
  const [trackedApps, setTrackedApps] = useState<TrackedApplication[]>([]);
  const [kanbanLoading, setKanbanLoading] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const API_BASE = "http://localhost:8000";

  // Check authentication on startup
  useEffect(() => {
    const savedEmail = localStorage.getItem("honestmatch_auth_email");
    if (savedEmail) {
      setEmail(savedEmail);
      setIsAuthenticated(true);
    }
  }, []);

  // Trigger matches & portfolio reload on email change
  useEffect(() => {
    if (email && isAuthenticated) {
      reloadData();
    }
  }, [email, isAuthenticated]);

  // Load outreach notes when active selection matches change
  useEffect(() => {
    if (selectedMatch && isAuthenticated) {
      fetchOutreachDraft(selectedMatch.job.id);
    }
  }, [selectedMatch, isAuthenticated]);

  // Trigger tailoring or interview prep reload when tab changes
  useEffect(() => {
    if (selectedMatch && isAuthenticated) {
      if (activeTab === "tailoring") {
        fetchTailoring();
      } else if (activeTab === "prep") {
        fetchPrep();
      }
    }
  }, [selectedMatch, activeTab, isAuthenticated]);

  const reloadData = async () => {
    await fetchUserProfile();
    await fetchResume();
    await fetchSearchProfile();
    await fetchCompanySignals();
    await fetchMatches();
    await fetchTrackedApplications();
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authInputEmail) return;
    if (!consentChecked) {
      alert("Please review and accept the Privacy Policy and DPDP/GDPR consent terms before signing in.");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: authInputEmail }),
      });
      if (res.ok) {
        localStorage.setItem("honestmatch_auth_email", authInputEmail);
        setEmail(authInputEmail);
        setIsAuthenticated(true);
      } else {
        alert("Failed to securely log in. Please verify your backend server is online.");
      }
    } catch (err) {
      alert("Backend server offline. Verify uvicorn is running on http://localhost:8000.");
    }
  };

  const handleSignOut = () => {
    localStorage.removeItem("honestmatch_auth_email");
    setEmail("");
    setAuthInputEmail("");
    setIsAuthenticated(false);
    setResume(null);
    setMatches([]);
    setSelectedMatch(null);
  };

  const fetchResume = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/resume?email=${encodeURIComponent(email)}`);
      if (res.ok) {
        const data = await res.json();
        setResume(data);
      }
    } catch (e) {
      console.log("No resume parsed yet.");
    }
  };

  const fetchSearchProfile = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/search_profile?email=${encodeURIComponent(email)}`);
      if (res.ok) {
        const data = await res.json();
        setIsRemotePref(data.is_remote);
        setLocationPref(data.location);
        setKeywordsPref(data.keywords);
      }
    } catch (e) {
      console.log("Could not load search preferences.");
    }
  };

  const fetchCompanySignals = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/signals`);
      if (res.ok) {
        const data = await res.json();
        setCompanySignals(data);
      }
    } catch (e) {
      console.log("Could not fetch active company signals.");
    }
  };

  const fetchTailoring = async () => {
    if (!selectedMatch) return;
    setTailoringLoading(true);
    setTailoringData([]);
    try {
      const res = await fetch(`${API_BASE}/api/resume/tailor`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, job_id: selectedMatch.job.id }),
      });
      if (res.ok) {
        const data = await res.json();
        setTailoringData(data.tailored_bullets);
      }
    } catch (e) {
      console.log("Error loading tailored bullets.");
    }
    setTailoringLoading(false);
  };

  const fetchPrep = async () => {
    if (!selectedMatch) return;
    setPrepLoading(true);
    setPrepQuestions([]);
    try {
      const res = await fetch(`${API_BASE}/api/interview/prep`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, job_id: selectedMatch.job.id }),
      });
      if (res.ok) {
        const data = await res.json();
        setPrepQuestions(data.questions);
      }
    } catch (e) {
      console.log("Error loading interview prep questions.");
    }
    setPrepLoading(false);
  };

  const fetchUserProfile = async () => {
    if (!email) return;
    try {
      const res = await fetch(`${API_BASE}/api/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (res.ok) {
        const data = await res.json();
        setSubscriptionTier(data.subscription_tier);
        setOutreachCount(data.outreach_count);
      }
    } catch (e) {
      console.log("Could not load user profile metadata.");
    }
  };

  const handleUpgradeTier = async (tier: "free" | "premium" | "executive") => {
    try {
      const res = await fetch(`${API_BASE}/api/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, tier }),
      });
      if (res.ok) {
        const data = await res.json();
        alert(data.message);
        setSubscriptionTier(data.tier);
        // Instant reload
        fetchUserProfile();
        fetchMatches();
      }
    } catch (e) {
      alert("Error upgrading subscription tier.");
    }
  };

  const handleSavePreferences = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingPrefs(true);
    try {
      const res = await fetch(`${API_BASE}/api/search_profile?email=${encodeURIComponent(email)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          is_remote: isRemotePref,
          location: locationPref,
          company_stage: "Any",
          keywords: keywordsPref
        }),
      });
      if (res.ok) {
        alert("✓ Saved search filters updated! Job curation queue instantly re-ranked.");
        await fetchMatches();
      }
    } catch (err) {
      alert("Failed to save search profile preferences.");
    }
    setIsSavingPrefs(false);
  };

  const handleTriggerDigest = async () => {
    setIsSendingDigest(true);
    try {
      const res = await fetch(`${API_BASE}/api/digest/send?email=${encodeURIComponent(email)}`, {
        method: "POST"
      });
      if (res.ok) {
        alert("✓ Curated Monday Digest Compiled & Transmitted Successfully!\n\nEmail file written to logs/weekly_digest_emails.log");
      } else {
        alert("Verify you have uploaded a candidate resume to generate matches digest.");
      }
    } catch (e) {
      alert("Error triggering weekly digest compiled dispatch.");
    }
    setIsSendingDigest(false);
  };

  const fetchMatches = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/jobs/matches?email=${encodeURIComponent(email)}`);
      if (res.ok) {
        const data = await res.json();
        setMatches(data);
        if (data.length > 0 && !selectedMatch) {
          setSelectedMatch(data[0]);
        }
      }
    } catch (e) {
      console.log("Could not load job matches.");
    }
  };

  const fetchTrackedApplications = async () => {
    setKanbanLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/applications?email=${encodeURIComponent(email)}`);
      if (res.ok) {
        const data = await res.json();
        setTrackedApps(data);
      }
    } catch (e) {
      console.log("Could not fetch tracked applications.");
    }
    setKanbanLoading(false);
  };

  const fetchOutreachDraft = async (jobId: string) => {
    setOutreachLoading(true);
    setOutreachData(null);
    try {
      const res = await fetch(`${API_BASE}/api/outreach/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, job_id: jobId }),
      });
      if (res.ok) {
        const data = await res.json();
        setOutreachData(data);
      }
    } catch (e) {
      console.log("Error generating outreach note draft.");
    }
    setOutreachLoading(false);
  };

  const handleSyncJobs = async () => {
    setIsSyncing(true);
    setSyncMessage("Syncing active Greenhouse & Lever listings...");
    try {
      const res = await fetch(`${API_BASE}/api/jobs/sync`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setSyncMessage(`Sync complete! Loaded new listings & active AI Signals.`);
        await reloadData();
      } else {
        setSyncMessage("API offline. Loading premium local mock jobs...");
        await fetch(`${API_BASE}/api/jobs/sync?force_mock=true`, { method: "POST" });
        await reloadData();
      }
    } catch (e) {
      setSyncMessage("Error connecting to FastAPI backend.");
    }
    setIsSyncing(false);
    setTimeout(() => setSyncMessage(""), 5000);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const file = files[0];
    
    setIsUploading(true);
    setUploadError("");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/resume/upload?email=${encodeURIComponent(email)}`, {
        method: "POST",
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        setResume(data);
        setActiveMainView("curation");
        setActiveTab("matching");
        await reloadData();
      } else {
        const err = await res.json();
        setUploadError(err.detail || "Error parsing resume.");
      }
    } catch (e) {
      setUploadError("Could not reach parser server. Verify backend is running on port 8000.");
    }
    setIsUploading(false);
  };

  const triggerFileInput = () => {
    fileInputRef.current?.click();
  };

  const handleTrackApplication = async (jobId: string, status: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/applications?email=${encodeURIComponent(email)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, status }),
      });
      if (res.ok) {
        await fetchTrackedApplications();
        alert(`Job status updated to "${status}" successfully!`);
      }
    } catch (e) {
      alert("Error saving application status.");
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return "text-emerald-400 border-emerald-500/30 bg-emerald-500/10";
    if (score >= 50) return "text-amber-400 border-amber-500/30 bg-amber-500/10";
    return "text-rose-400 border-rose-500/30 bg-rose-500/10";
  };

  const kanbanColumns = [
    { key: "prioritized", label: "Prioritized Queue", border: "border-t-cyan-500", bg: "bg-cyan-500/5" },
    { key: "applied", label: "Applied", border: "border-t-sky-500", bg: "bg-sky-500/5" },
    { key: "interviewing", label: "Interviewing", border: "border-t-amber-500", bg: "bg-amber-500/5" },
    { key: "complete", label: "Offers / Complete", border: "border-t-emerald-500", bg: "bg-emerald-500/5" }
  ];

  const getJobsByStatus = (statusKey: string) => {
    if (statusKey === "prioritized") {
      const trackedJobIds = new Set(trackedApps.map(a => a.job.id));
      const untrackedMatches = matches.filter(m => !trackedJobIds.has(m.job.id)).map(m => ({
        id: `match-${m.job.id}`,
        job: m.job,
        status: "prioritized",
        match_score: m.match_score
      }));
      
      const explicitlyTracked = trackedApps.filter(a => a.status === "prioritized").map(a => {
        const matchData = matches.find(m => m.job.id === a.job.id);
        return {
          id: a.id,
          job: a.job,
          status: a.status,
          match_score: matchData ? matchData.match_score : 50
        };
      });
      
      return [...explicitlyTracked, ...untrackedMatches];
    } else {
      return trackedApps.filter(a => a.status === statusKey).map(a => {
        const matchData = matches.find(m => m.job.id === a.job.id);
        return {
          id: a.id,
          job: a.job,
          status: a.status,
          match_score: matchData ? matchData.match_score : 50
        };
      });
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans justify-center items-center p-6 select-none relative overflow-hidden">
        <div className="absolute top-1/4 left-1/4 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl"></div>
        <div className="absolute bottom-1/4 right-1/4 translate-x-1/2 translate-y-1/2 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl"></div>

        <div className="w-full max-w-md bg-slate-900/60 backdrop-blur-xl border border-slate-800 p-8 rounded-3xl shadow-2xl relative z-10 flex flex-col gap-6">
          
          <div className="text-center flex flex-col gap-2">
            <div className="h-12 w-12 rounded-2xl bg-gradient-to-tr from-cyan-500 to-indigo-500 flex items-center justify-center font-bold text-slate-950 text-2xl shadow-xl shadow-cyan-500/20 mx-auto">
              H
            </div>
            <h1 className="text-2xl font-black bg-gradient-to-r from-white via-cyan-100 to-indigo-200 bg-clip-text text-transparent mt-2">
              HonestMatch AI Platform
            </h1>
            <p className="text-xs text-slate-400">Secure Passwordless Candidate Access Portal</p>
          </div>

          <form onSubmit={handleLogin} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Candidate Email</label>
              <input 
                type="email"
                required
                value={authInputEmail}
                onChange={(e) => setAuthInputEmail(e.target.value)}
                placeholder="meenan.iitk@gmail.com"
                className="bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-cyan-300 placeholder-slate-600 focus:outline-none focus:border-cyan-500 transition-all font-semibold"
              />
            </div>

            <div className="flex items-start gap-3 bg-slate-950/60 border border-slate-800/80 p-3.5 rounded-xl">
              <input 
                type="checkbox"
                id="consent-check"
                checked={consentChecked}
                onChange={(e) => setConsentChecked(e.target.checked)}
                className="mt-1 accent-cyan-500 h-4 w-4 bg-transparent border-slate-800 rounded"
              />
              <label htmlFor="consent-check" className="text-[11px] text-slate-400 leading-relaxed cursor-pointer select-none">
                I hereby declare explicit, unambiguous consent to process my uploaded PDF resumes for AI structured matching and connection notes, in strict compliance with the **India DPDP Act (2023)** and **GDPR Privacy Terms**.
              </label>
            </div>

            <button 
              type="submit"
              className="w-full py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-indigo-500 text-slate-950 font-black text-sm transition-all hover:opacity-95 shadow-lg shadow-cyan-500/10 active:scale-98"
            >
              Sign In Securely
            </button>
          </form>

          <div className="border-t border-slate-850 pt-4 text-center">
            <p className="text-[10px] text-slate-500 leading-relaxed">
              🔒 All raw resumes are protected with field-level symmetric AES encryption at rest in our databases.
            </p>
          </div>

        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-cyan-500 selection:text-slate-900">
      
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-40 px-6 py-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-500 flex items-center justify-center font-bold text-slate-950 text-xl shadow-lg shadow-cyan-500/20">
            H
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-slate-50 via-cyan-200 to-indigo-300 bg-clip-text text-transparent">
              HonestMatch AI
            </h1>
            <p className="text-xs text-slate-400">Zero-fluff Job Matching & Gap Analysis</p>
          </div>
        </div>

        <div className="flex bg-slate-900 border border-slate-800 p-1 rounded-xl">
          <button 
            onClick={() => setActiveMainView("curation")}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${activeMainView === "curation" ? "bg-cyan-500 text-slate-950" : "text-slate-400 hover:text-slate-200"}`}
          >
            🎯 Curation Queue
          </button>
          <button 
            onClick={() => setActiveMainView("kanban")}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${activeMainView === "kanban" ? "bg-cyan-500 text-slate-950" : "text-slate-400 hover:text-slate-200"}`}
          >
            📋 Kanban Status Board
          </button>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center bg-slate-800/80 border border-slate-700/60 rounded-lg px-3 py-1.5 gap-2">
            <span className="text-xs text-slate-400 font-medium">Session:</span>
            <span className="text-xs text-cyan-300 font-bold">{email}</span>
          </div>

          <button 
            onClick={handleSignOut}
            className="px-3 py-1.5 rounded-lg border border-red-500/20 hover:border-red-500 bg-red-950/20 hover:bg-red-950/60 text-xs font-semibold text-red-400 transition-all"
          >
            Sign Out
          </button>

          {/* Trigger Monday Morning Digest Button (Month 4 Retention Engine) */}
          <button 
            onClick={handleTriggerDigest}
            disabled={isSendingDigest}
            className="px-4 py-1.5 rounded-lg border border-cyan-500/20 hover:border-cyan-500 bg-cyan-950/20 hover:bg-cyan-950/60 text-xs font-bold text-cyan-400 transition-all"
          >
            {isSendingDigest ? "Compiling..." : "Trigger Digest Email"}
          </button>

          <button 
            onClick={handleSyncJobs}
            disabled={isSyncing}
            className="px-4 py-1.5 rounded-lg border border-slate-700 hover:border-slate-500 bg-slate-900 hover:bg-slate-800 text-xs font-semibold text-slate-200 hover:text-white transition-all disabled:opacity-50"
          >
            {isSyncing ? "Syncing..." : "Sync ATS Jobs"}
          </button>
        </div>
      </header>

      {/* 💳 Month 6 SaaS Subscription & Monetization Status Bar */}
      <div className="bg-slate-900/60 border-b border-slate-800/80 px-6 py-3 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-slate-400 font-semibold">Subscription Plan:</span>
          <span className={`px-2.5 py-0.5 rounded-full text-xs font-extrabold uppercase tracking-wide border shadow-md font-mono ${
            subscriptionTier === "executive" 
              ? "bg-purple-950/60 border-purple-500/40 text-purple-300 shadow-purple-900/20" 
              : subscriptionTier === "premium" 
                ? "bg-cyan-950/60 border-cyan-500/40 text-cyan-300 shadow-cyan-900/20" 
                : "bg-slate-950/60 border-slate-800 text-slate-400"
          }`}>
            {subscriptionTier} Tier
          </span>

          {/* Usage Counters */}
          <div className="flex items-center gap-4 text-xs font-mono pl-4 border-l border-slate-800">
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Fit Scores:</span>
              <span className={`font-bold ${matches.length >= 5 && subscriptionTier === "free" ? "text-rose-400" : "text-slate-300"}`}>
                {matches.length} {subscriptionTier === "free" ? "/ 5" : "(Unlimited)"}
              </span>
            </div>
            <div className="flex items-center gap-1.5 pl-4 border-l border-slate-850">
              <span className="text-slate-500">Outreach Drafts:</span>
              <span className={`font-bold ${outreachCount >= 2 && subscriptionTier === "free" ? "text-rose-400" : "text-slate-300"}`}>
                {outreachCount} {subscriptionTier === "free" ? "/ 2" : "(Unlimited)"}
              </span>
            </div>
          </div>
        </div>

        {/* Action Upgrade Buttons */}
        <div className="flex items-center gap-2">
          {subscriptionTier === "free" && (
            <>
              <button 
                onClick={() => handleUpgradeTier("premium")}
                className="px-3.5 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-bold transition-all shadow-md shadow-cyan-500/10 flex items-center gap-1"
              >
                ⭐ Go Premium ($19/mo)
              </button>
              <button 
                onClick={() => handleUpgradeTier("executive")}
                className="px-3.5 py-1.5 rounded-lg bg-purple-500 hover:bg-purple-400 text-slate-950 text-xs font-bold transition-all shadow-md shadow-purple-500/10 flex items-center gap-1"
              >
                👑 Go Executive ($49/mo)
              </button>
            </>
          )}
          {subscriptionTier === "premium" && (
            <button 
              onClick={() => handleUpgradeTier("executive")}
              className="px-3.5 py-1.5 rounded-lg bg-purple-500 hover:bg-purple-400 text-slate-950 text-xs font-bold transition-all shadow-md shadow-purple-500/10 flex items-center gap-1"
            >
              👑 Go Executive ($49/mo)
            </button>
          )}
          {(subscriptionTier === "premium" || subscriptionTier === "executive") && (
            <button 
              onClick={() => handleUpgradeTier("free")}
              className="px-2.5 py-1 rounded-lg border border-slate-800 hover:border-slate-700 bg-slate-950/60 text-slate-500 hover:text-slate-400 text-[10px] font-mono transition-all"
            >
              Cancel Subscription
            </button>
          )}
        </div>
      </div>

      {syncMessage && (
        <div className="bg-cyan-950/70 border-b border-cyan-500/20 text-cyan-200 text-xs py-2 px-6 text-center animate-fade-in font-medium">
          🚀 {syncMessage}
        </div>
      )}

      {activeMainView === "curation" ? (
        <main className="flex-1 max-w-7xl w-full mx-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
          
          <section className="lg:col-span-5 flex flex-col gap-6">
            
            <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-5 flex flex-col gap-4">
              <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">Resume Matching Node</h2>
              
              <div 
                onClick={triggerFileInput}
                className="border-2 border-dashed border-slate-800 hover:border-cyan-500/50 bg-slate-950/80 rounded-xl p-6 text-center cursor-pointer transition-all hover:bg-slate-900/30 group"
              >
                <input 
                  type="file" 
                  ref={fileInputRef} 
                  onChange={handleFileUpload} 
                  accept=".pdf" 
                  className="hidden" 
                />
                <div className="h-12 w-12 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center mx-auto mb-3 group-hover:border-cyan-500/30 group-hover:bg-cyan-950/20 transition-all text-slate-400 group-hover:text-cyan-400">
                  📄
                </div>
                <p className="text-sm font-semibold text-slate-200 group-hover:text-white">
                  {isUploading ? "Extracting structures via Gemini..." : "Upload Candidate Resume PDF"}
                </p>
                <p className="text-xs text-slate-500 mt-1">Accepts B.Tech / ML Engineer PDF profiles</p>
              </div>

              {uploadError && (
                <p className="text-xs text-rose-400 bg-rose-950/20 border border-rose-800/30 p-2 rounded-lg">{uploadError}</p>
              )}

              {resume && (
                <div className="flex items-center justify-between border-t border-slate-800/60 pt-3">
                  <div className="flex items-center gap-2">
                    <span className="text-emerald-400">✓</span>
                    <span className="text-xs font-semibold text-slate-300">{resume.structured_json.name}</span>
                  </div>
                  <span className="text-[10px] text-slate-500">Updated: {new Date(resume.updated_at).toLocaleDateString()}</span>
                </div>
              )}
            </div>

            <div className="bg-slate-900/40 border border-slate-800 rounded-2xl flex-1 flex flex-col overflow-hidden min-h-[450px]">
              <div className="p-4 border-b border-slate-800/80 flex items-center justify-between">
                <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">Top 10 Curation Queue</h2>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">Honest Metric</span>
              </div>

              {matches.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
                  <p className="text-slate-500 text-sm">No matches calculated yet.</p>
                  <p className="text-xs text-slate-600 mt-1">Please upload a resume above or sync jobs to initiate.</p>
                </div>
              ) : (
                <div className="flex-1 overflow-y-auto divide-y divide-slate-800/60">
                  {matches.map((match) => (
                    <div 
                      key={match.job.id}
                      onClick={() => setSelectedMatch(match)}
                      className={`p-4 flex items-center justify-between cursor-pointer transition-all hover:bg-slate-800/20 ${selectedMatch?.job.id === match.job.id ? "bg-slate-800/35 border-l-2 border-cyan-400" : ""}`}
                    >
                      <div className="flex flex-col gap-1 w-3/4">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 font-bold">{match.job.company}</span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-300 uppercase font-semibold">{match.job.ats_type}</span>
                        </div>
                        <span className="text-sm font-bold text-slate-100 hover:text-white truncate">{match.job.title}</span>
                      </div>

                      <div className={`h-11 w-11 rounded-xl border flex flex-col items-center justify-center font-bold font-mono text-sm tracking-tighter ${getScoreColor(match.match_score)}`}>
                        {match.match_score}%
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="lg:col-span-7 flex flex-col gap-6">
            
            {selectedMatch ? (
              <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-6 flex flex-col gap-6 min-h-[500px]">
                
                <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800/60 pb-5">
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-2xl font-bold tracking-tight text-white">{selectedMatch.job.company}</h3>
                      <a 
                        href={selectedMatch.job.url} 
                        target="_blank" 
                        rel="noopener noreferrer" 
                        className="text-xs text-cyan-400 hover:underline flex items-center gap-0.5"
                      >
                        Apply Link ↗
                      </a>
                    </div>
                    <p className="text-lg font-semibold text-slate-200">{selectedMatch.job.title}</p>
                  </div>

                  <div className="flex flex-col items-end gap-1">
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500">Brutal Match Rating</span>
                    <div className={`px-4 py-1.5 rounded-full border text-sm font-bold font-mono ${getScoreColor(selectedMatch.match_score)}`}>
                      {selectedMatch.match_score}% Fit Score
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 border-b border-slate-800/40 pb-3">
                  <button 
                    onClick={() => setActiveTab("matching")}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === "matching" ? "bg-cyan-500 text-slate-950 font-bold" : "bg-slate-800 text-slate-400 hover:bg-slate-750"}`}
                  >
                    Honest Gap Analysis
                  </button>
                  {resume && (
                    <button 
                      onClick={() => setActiveTab("profile")}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === "profile" ? "bg-cyan-500 text-slate-950 font-bold" : "bg-slate-800 text-slate-400 hover:bg-slate-750"}`}
                    >
                      Structured Candidate Profile
                    </button>
                  )}
                  {resume && (
                    <button 
                      onClick={() => setActiveTab("tailoring")}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === "tailoring" ? "bg-cyan-500 text-slate-950 font-bold" : "bg-slate-800 text-slate-400 hover:bg-slate-750"}`}
                    >
                      🛠️ Resume Tailoring
                    </button>
                  )}
                  {resume && (
                    <button 
                      onClick={() => setActiveTab("prep")}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === "prep" ? "bg-cyan-500 text-slate-950 font-bold" : "bg-slate-800 text-slate-400 hover:bg-slate-750"}`}
                    >
                      🎤 Interview Prep
                    </button>
                  )}
                  <button 
                    onClick={() => setActiveTab("preferences")}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === "preferences" ? "bg-cyan-500 text-slate-950 font-bold" : "bg-slate-800 text-slate-400 hover:bg-slate-750"}`}
                  >
                    Saved Search Preferences
                  </button>
                </div>

                {activeTab === "matching" ? (
                  <div className="flex flex-col gap-6">
                    
                    <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-5 flex flex-col gap-4">
                      <div className="flex items-center justify-between">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Identified Gaps</h4>
                        <span className="text-[10px] text-rose-400 font-semibold uppercase">Brutal Penalty Applied</span>
                      </div>

                      {selectedMatch.gaps.missing_skills.length === 0 ? (
                        <p className="text-sm text-emerald-400 font-medium">✓ No major skill gaps found. Your technical profile aligns perfectly with this role's description!</p>
                      ) : (
                        <div className="flex flex-col gap-3">
                          <div className="flex flex-wrap gap-2">
                            {selectedMatch.gaps.missing_skills.map((skill, index) => (
                              <span 
                                key={index}
                                className="px-2.5 py-1 rounded bg-rose-950/30 border border-rose-800/30 text-rose-400 text-xs font-bold font-mono"
                              >
                                - {skill}
                              </span>
                            ))}
                          </div>
                          
                          <div className="border-t border-slate-800/60 pt-3">
                            <span className="text-xs font-bold text-slate-400">Actionable Resume Optimization Advice:</span>
                            <p className="text-xs text-slate-300 mt-1 italic leading-relaxed">
                              {selectedMatch.gaps.resume_optimization}
                            </p>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 📊 Month 7-12: Direct Company Intelligence & ATS Dynamics */}
                    {selectedMatch.ats_dynamics && (
                      <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-5 flex flex-col gap-3">
                        <div className="flex items-center justify-between border-b border-slate-800/60 pb-2">
                          <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">📊 Direct Company Intelligence & ATS Dynamics</h4>
                          <span className="text-[10px] text-cyan-400 font-mono font-bold uppercase">Greenhouse Ingestion Active</span>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div className="flex flex-col gap-1">
                            <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">ATS Urgency Signal</span>
                            <span className={`text-xs font-bold ${selectedMatch.ats_dynamics.urgency.includes("High") ? "text-amber-400" : "text-slate-300"}`}>
                              ⚡ {selectedMatch.ats_dynamics.urgency}
                            </span>
                          </div>
                          <div className="flex flex-col gap-1">
                            <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Historical Pipeline Status</span>
                            <span className={`text-xs font-bold ${selectedMatch.ats_dynamics.status === "Stale" ? "text-rose-400" : "text-emerald-400"}`}>
                              ⏺ {selectedMatch.ats_dynamics.status} ({selectedMatch.ats_dynamics.days_open} Days Open)
                            </span>
                          </div>
                        </div>
                        <div className="border-t border-slate-800/60 pt-2 mt-1">
                          <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Greenhouse/Lever Closing Patterns</span>
                          <p className="text-xs text-slate-300 font-medium mt-0.5">
                            🕵️‍♂️ {selectedMatch.ats_dynamics.hiring_signal}
                          </p>
                        </div>
                      </div>
                    )}

                    <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-5 flex flex-col gap-4">
                      <div className="flex items-center justify-between border-b border-slate-800/60 pb-2">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Outreach Generator Node</h4>
                        {outreachData && (
                          <button 
                            onClick={() => {
                              navigator.clipboard.writeText(outreachData.linkedin_note);
                              alert("Outreach message copied to clipboard!");
                            }}
                            className="text-[10px] text-cyan-400 font-bold hover:underline"
                          >
                            Copy Draft
                          </button>
                        )}
                      </div>

                      {outreachLoading ? (
                        <div className="py-4 text-center flex items-center justify-center gap-2">
                          <div className="h-4 w-4 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin"></div>
                          <span className="text-xs text-slate-400">Drafting personalized notes via Gemini...</span>
                        </div>
                      ) : outreachData ? (
                        <div className="flex flex-col gap-4 animate-fade-in">
                          <div>
                            <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Target Company Intel</span>
                            <p className="text-xs text-slate-300 mt-1 font-semibold leading-relaxed">
                              {outreachData.company_summary}
                            </p>
                          </div>
                          
                          <div>
                            <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Tailored 300-Char Connection Note</span>
                            <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 text-xs text-cyan-200 leading-relaxed font-mono mt-1 relative">
                              "{outreachData.linkedin_note}"
                              <span className="absolute bottom-1 right-2 text-[9px] text-slate-500 font-mono">
                                {outreachData.linkedin_note.length} / 300 chars
                              </span>
                            </div>
                          </div>
                          <span className="text-[10px] text-slate-500 leading-relaxed">
                            💡 <strong>Note:</strong> Send this manually on LinkedIn to avoid platform automation detection bans.
                          </span>
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500 text-center">Failed to load outreach note.</p>
                      )}
                    </div>

                    <div className="flex flex-wrap gap-2 border-t border-slate-800/60 pt-4">
                      <button 
                        onClick={() => handleTrackApplication(selectedMatch.job.id, "applied")}
                        className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-bold transition-all shadow-md shadow-cyan-500/10"
                      >
                        Track: Applied
                      </button>
                      <button 
                        onClick={() => handleTrackApplication(selectedMatch.job.id, "interviewing")}
                        className="px-4 py-2 rounded-lg border border-slate-700 hover:border-slate-500 bg-slate-900 text-slate-300 hover:text-white text-xs font-semibold transition-all"
                      >
                        Track: Interviewing
                      </button>
                      <button 
                        onClick={() => handleTrackApplication(selectedMatch.job.id, "complete")}
                        className="px-4 py-2 rounded-lg border border-slate-700 hover:border-slate-500 bg-slate-900 text-slate-300 hover:text-white text-xs font-semibold transition-all"
                      >
                        Track: Offer / Complete
                      </button>
                    </div>

                  </div>
                ) : activeTab === "profile" ? (
                  resume && (
                    <div className="flex flex-col gap-5 text-xs">
                      
                      <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 flex flex-col gap-2">
                        <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Skills Extracted</span>
                        <div className="flex flex-wrap gap-1.5">
                          {resume.structured_json.skills.map((s, idx) => (
                            <span key={idx} className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700/60 text-slate-300">{s}</span>
                          ))}
                        </div>
                      </div>

                      <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 flex flex-col gap-3">
                        <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Extracted Experience</span>
                        <div className="divide-y divide-slate-800/60 flex flex-col gap-3">
                          {resume.structured_json.experience.length === 0 ? (
                            <p className="text-slate-500">No experience extracted.</p>
                          ) : (
                            resume.structured_json.experience.map((exp, idx) => (
                              <div key={idx} className={`${idx > 0 ? "pt-3" : ""} flex flex-col gap-1`}>
                                <div className="flex items-center justify-between font-bold text-slate-200">
                                  <span>{exp.role} @ {exp.company}</span>
                                  <span className="text-[10px] text-slate-500">{exp.duration}</span>
                                </div>
                                <p className="text-slate-400 text-[11px] leading-relaxed">{exp.description}</p>
                              </div>
                            ))
                          )}
                        </div>
                      </div>

                      <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 flex flex-col gap-2">
                        <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Education</span>
                        {resume.structured_json.education.map((edu, idx) => (
                          <div key={idx} className="flex justify-between font-medium text-slate-300">
                            <span>{edu.degree} — {edu.institution}</span>
                            <span className="text-slate-500">{edu.year}</span>
                          </div>
                        ))}
                      </div>

                    </div>
                  )
                ) : activeTab === "preferences" ? (
                  <div className="flex flex-col gap-6 animate-fade-in">
                    
                    {/* Saved Search Preferences Form */}
                    <form onSubmit={handleSavePreferences} className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-5 flex flex-col gap-4">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Search Preference Filters</h4>
                      
                      <div className="flex items-center gap-3">
                        <input 
                          type="checkbox"
                          id="remote-pref-check"
                          checked={isRemotePref}
                          onChange={(e) => setIsRemotePref(e.target.checked)}
                          className="accent-cyan-500 h-4 w-4 bg-transparent border-slate-800 rounded"
                        />
                        <label htmlFor="remote-pref-check" className="text-xs font-bold text-slate-300 cursor-pointer">
                          Prioritize and soft-filter Remote Positions (+10 remote boost, -15 non-remote penalty)
                        </label>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="flex flex-col gap-1.5">
                          <label className="text-[10px] font-bold text-slate-500 uppercase">Target Location Preference</label>
                          <input 
                            type="text"
                            value={locationPref}
                            onChange={(e) => setLocationPref(e.target.value)}
                            placeholder="e.g. India, Bengaluru, US"
                            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-cyan-300 placeholder-slate-700 focus:outline-none focus:border-cyan-500 transition-all font-semibold"
                          />
                        </div>

                        <div className="flex flex-col gap-1.5">
                          <label className="text-[10px] font-bold text-slate-500 uppercase">Priority Technical Keywords</label>
                          <input 
                            type="text"
                            value={keywordsPref}
                            onChange={(e) => setKeywordsPref(e.target.value)}
                            placeholder="e.g. Kubernetes, React, MLOps"
                            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-cyan-300 placeholder-slate-700 focus:outline-none focus:border-cyan-500 transition-all font-semibold"
                          />
                        </div>
                      </div>

                      <button 
                        type="submit"
                        disabled={isSavingPrefs}
                        className="self-start px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-bold transition-all disabled:opacity-50"
                      >
                        {isSavingPrefs ? "Saving..." : "Save Preferences & Re-Rank"}
                      </button>
                    </form>

                    {/* Active AI Company Signals List */}
                    <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-5 flex flex-col gap-3">
                      <div className="flex items-center justify-between border-b border-slate-850 pb-2">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Tracked AI Company Signals</h4>
                        <span className="text-[10px] text-cyan-400 font-bold font-mono">Algorithmic Moat Boosts</span>
                      </div>

                      {companySignals.length === 0 ? (
                        <p className="text-xs text-slate-600 italic">No signals synced. Run sync ATS jobs to load high-signal funding datasets.</p>
                      ) : (
                        <div className="flex flex-col gap-3 max-h-[250px] overflow-y-auto">
                          {companySignals.map((sig) => (
                            <div key={sig.id} className="border border-slate-850 bg-slate-900/60 rounded-lg p-3 flex justify-between items-start gap-4">
                              <div className="flex flex-col gap-1 text-xs">
                                <div className="flex items-center gap-2">
                                  <span className="font-bold text-slate-200">{sig.company}</span>
                                  <span className="text-[9px] px-1.5 bg-slate-800 rounded text-slate-400 uppercase font-semibold">{sig.signal_type}</span>
                                </div>
                                <p className="text-[11px] text-slate-400 leading-relaxed">{sig.description}</p>
                              </div>
                              <span className="text-xs font-bold text-emerald-400 bg-emerald-950/40 border border-emerald-800/20 px-2 py-0.5 rounded-md font-mono shrink-0">
                                +{sig.weight_boost}% Boost
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                  </div>
                ) : activeTab === "tailoring" ? (
                  /* 🛠️ Month 5 Dynamic Resume Tailoring Tab */
                  <div className="flex flex-col gap-5 animate-fade-in">
                    <div className="flex items-center justify-between border-b border-slate-850 pb-2">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Dynamic Resume Tailoring Suggestions</h4>
                      <span className="text-[10px] text-cyan-400 font-bold font-mono">Context-Aware AI Rewrites</span>
                    </div>

                    {tailoringLoading ? (
                      <div className="py-12 text-center flex items-center justify-center gap-2">
                        <div className="h-6 w-6 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin"></div>
                        <span className="text-xs text-slate-400 font-semibold">Generating bullet point rewrites...</span>
                      </div>
                    ) : tailoringData.length === 0 ? (
                      <p className="text-xs text-slate-500 text-center italic">Failed to calculate tailoring options.</p>
                    ) : (
                      <div className="flex flex-col gap-4">
                        {tailoringData.map((item, idx) => (
                          <div key={idx} className="border border-slate-850 bg-slate-950/60 rounded-xl p-4 flex flex-col gap-3">
                            <div>
                              <span className="text-[10px] uppercase font-bold text-rose-400 tracking-wider font-mono">Original Resume Bullet</span>
                              <p className="text-xs text-slate-400 mt-1 leading-relaxed">{item.original_bullet}</p>
                            </div>
                            
                            <div className="border-t border-slate-850 pt-2 relative">
                              <span className="text-[10px] uppercase font-bold text-emerald-400 tracking-wider font-mono">Suggested Tailored Bullet Rewrite</span>
                              <p className="text-xs text-slate-200 mt-1 leading-relaxed font-medium bg-slate-900 border border-slate-850 p-2.5 rounded-lg select-all">
                                {item.tailored_bullet}
                              </p>
                              <button 
                                type="button"
                                onClick={() => {
                                  navigator.clipboard.writeText(item.tailored_bullet);
                                  alert("Tailored bullet copied!");
                                }}
                                className="absolute top-2 right-2 text-[9px] text-cyan-400 font-bold hover:underline"
                              >
                                Copy Bullet
                              </button>
                            </div>

                            <div className="border-t border-slate-850 pt-2">
                              <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Consultant Rationale</span>
                              <p className="text-[11px] text-slate-400 mt-1 italic">{item.rationale}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  /* 🎤 Month 5 Interview Prep Tab */
                  <div className="flex flex-col gap-5 animate-fade-in">
                    <div className="flex items-center justify-between border-b border-slate-850 pb-2">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Customized Interview Preparation Guide</h4>
                      <span className="text-[10px] text-cyan-400 font-bold font-mono">10 Curated STAR Questions</span>
                    </div>

                    {prepLoading ? (
                      <div className="py-12 text-center flex items-center justify-center gap-2">
                        <div className="h-6 w-6 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin"></div>
                        <span className="text-xs text-slate-400 font-semibold">Compiling probable interview questions...</span>
                      </div>
                    ) : prepQuestions.length === 0 ? (
                      <p className="text-xs text-slate-500 text-center italic">Failed to calculate prep guide.</p>
                    ) : (
                      <div className="flex flex-col gap-4 max-h-[500px] overflow-y-auto pr-1">
                        {prepQuestions.map((q) => (
                          <div key={q.id} className="border border-slate-850 bg-slate-950/60 rounded-xl p-4 flex flex-col gap-2 animate-fade-in">
                            <div className="flex justify-between items-start gap-3">
                              <span className="text-xs font-bold text-slate-200">
                                {q.id}. {q.question}
                              </span>
                              <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono font-bold uppercase shrink-0 ${q.type === 'technical' ? 'bg-cyan-950 text-cyan-400' : 'bg-amber-950 text-amber-400'}`}>
                                {q.type}
                              </span>
                            </div>
                            
                            <div className="border-t border-slate-850 pt-2 grid grid-cols-1 md:grid-cols-12 gap-3 text-[11px]">
                              <div className="md:col-span-3 flex flex-col gap-0.5">
                                <span className="text-[9px] uppercase font-bold text-slate-500 tracking-wider">Framework</span>
                                <span className="font-bold text-slate-300">{q.suggested_framework}</span>
                              </div>
                              <div className="md:col-span-9 flex flex-col gap-0.5">
                                <span className="text-[9px] uppercase font-bold text-slate-500 tracking-wider">Resume Proof Points & Talking Points</span>
                                <p className="text-slate-400 leading-relaxed font-semibold italic">{q.talking_points}</p>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

              </div>
            ) : (
              <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-8 flex flex-col items-center justify-center text-center min-h-[500px]">
                <p className="text-slate-500 text-sm">Please select a job from the left queue to view details.</p>
              </div>
            )}

          </section>

        </main>
      ) : (
        <main className="flex-1 max-w-7xl w-full mx-auto p-6 flex flex-col gap-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold tracking-tight text-white">CRM Kanban Tracking Pipeline</h2>
              <p className="text-xs text-slate-400">Track and manage application lifecycles without ATS program limitations.</p>
            </div>
            <button 
              onClick={fetchTrackedApplications}
              className="px-3 py-1 bg-slate-900 border border-slate-800 hover:bg-slate-800 text-xs font-bold rounded-lg"
            >
              Refresh Board
            </button>
          </div>

          {kanbanLoading ? (
            <div className="flex-1 flex flex-col items-center justify-center py-20 gap-3">
              <div className="h-8 w-8 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin"></div>
              <span className="text-sm text-slate-400">Loading pipeline CRM columns...</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 flex-1">
              
              {kanbanColumns.map((col) => {
                const columnJobs = getJobsByStatus(col.key);
                return (
                  <div 
                    key={col.key}
                    className={`flex flex-col gap-4 border-t-4 ${col.border} ${col.bg} border border-slate-800/80 rounded-2xl p-4 min-h-[500px]`}
                  >
                    <div className="flex items-center justify-between border-b border-slate-850 pb-2">
                      <span className="text-sm font-bold text-slate-200">{col.label}</span>
                      <span className="text-xs font-bold px-2 py-0.5 bg-slate-900 rounded-full border border-slate-800 text-slate-400">
                        {columnJobs.length}
                      </span>
                    </div>

                    <div className="flex flex-col gap-3 overflow-y-auto flex-1 max-h-[600px] pr-1">
                      {columnJobs.length === 0 ? (
                        <div className="flex-1 flex items-center justify-center text-center p-6 border border-dashed border-slate-800/60 rounded-xl">
                          <span className="text-xs text-slate-600">No jobs in column</span>
                        </div>
                      ) : (
                        columnJobs.map((item) => (
                          <div 
                            key={item.id}
                            className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 flex flex-col gap-3 shadow-md hover:border-slate-700 transition-all group"
                          >
                            <div className="flex flex-col gap-0.5">
                              <span className="text-[10px] font-bold text-slate-400">{item.job.company}</span>
                              <span className="text-xs font-bold text-slate-100 group-hover:text-cyan-400 transition-colors truncate">{item.job.title}</span>
                            </div>

                            <div className="flex items-center justify-between">
                              <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 font-mono font-bold">
                                {item.match_score}% Fit
                              </span>
                              <a 
                                href={item.job.url} 
                                target="_blank" 
                                rel="noopener noreferrer" 
                                className="text-[10px] text-cyan-400 font-bold hover:underline"
                              >
                                Link ↗
                              </a>
                            </div>

                            <div className="border-t border-slate-850 pt-2 flex items-center justify-between gap-1">
                              <span className="text-[9px] text-slate-500">Move:</span>
                              <div className="flex gap-1">
                                {col.key !== "prioritized" && (
                                  <button 
                                    onClick={() => handleTrackApplication(item.job.id, "prioritized")}
                                    className="p-1 rounded bg-slate-850 hover:bg-slate-800 text-[9px] font-bold text-slate-400"
                                    title="Move to Prioritized"
                                  >
                                    ↩
                                  </button>
                                )}
                                {col.key !== "applied" && (
                                  <button 
                                    onClick={() => handleTrackApplication(item.job.id, "applied")}
                                    className="px-1.5 py-0.5 rounded bg-sky-950/60 hover:bg-sky-900 border border-sky-800/30 text-[9px] font-bold text-sky-400"
                                  >
                                    Applied
                                  </button>
                                )}
                                {col.key !== "interviewing" && (
                                  <button 
                                    onClick={() => handleTrackApplication(item.job.id, "interviewing")}
                                    className="px-1.5 py-0.5 rounded bg-amber-950/60 hover:bg-amber-900 border border-amber-800/30 text-[9px] font-bold text-amber-400"
                                  >
                                    Intv
                                  </button>
                                )}
                                {col.key !== "complete" && (
                                  <button 
                                    onClick={() => handleTrackApplication(item.job.id, "complete")}
                                    className="px-1.5 py-0.5 rounded bg-emerald-950/60 hover:bg-emerald-900 border border-emerald-800/30 text-[9px] font-bold text-emerald-400"
                                  >
                                    Offer
                                  </button>
                                )}
                              </div>
                            </div>

                          </div>
                        ))
                      )}
                    </div>

                  </div>
                );
              })}

            </div>
          )}

        </main>
      )}

      <footer className="border-t border-slate-900 bg-slate-950 py-4 px-6 text-center text-xs text-slate-600">
        HonestMatch AI Platform • Built for Solo Founders targeting funded startups in India & US.
      </footer>

    </div>
  );
}
