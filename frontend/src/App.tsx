import React, { useState, useEffect, useRef } from "react";
import { 
  Upload, ArrowDownRight, ArrowUpRight, 
  TrendingUp, AlertTriangle, CheckCircle, 
  Plus, Edit2, Search, Loader2
} from "lucide-react";
import { 
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, 
  LineChart, Line, CartesianGrid, Legend, Cell 
} from "recharts";

const API_BASE = "http://localhost:8000/api";

interface Transaction {
  id: string;
  date: string;
  description: string;
  amount: number;
  balance_after?: number;
  category?: string;
  source: string;
  account_id?: string;
  linked_transaction_id?: string;
}

interface Category {
  name: string;
  description?: string;
  is_custom: boolean;
}

interface Insight {
  category: string;
  correlation: number;
  impact_level: string;
  savings_rate_impact: number;
  recommendation: string;
}

export default function App() {
  // App States
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [accounts, setAccounts] = useState<string[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>("consolidated");
  
  // UI & Loading States
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [uploadResult, setUploadResult] = useState<{
    imported: number;
    duplicates: number;
  } | null>(null);
  const [aiConfirmModal, setAiConfirmModal] = useState<{
    fileId: string;
    cost: number;
    filename: string;
  } | null>(null);

  // Search & Filter States
  const [searchTerm, setSearchTerm] = useState("");
  const [filterCategory, setFilterCategory] = useState("all");
  const [sortField] = useState<"date" | "amount">("date");
  const [sortOrder] = useState<"asc" | "desc">("desc");

  // Inline Editing & Rules States
  const [editingTxId, setEditingTxId] = useState<string | null>(null);
  const [overrideModal, setOverrideModal] = useState<{
    txId: string;
    description: string;
    newCategory: string;
  } | null>(null);

  // Linking States
  const [activeLinkingTxId, setActiveLinkingTxId] = useState<string | null>(null);
  const [linkCandidates, setLinkCandidates] = useState<Transaction[]>([]);
  const [candidateLoading, setCandidateLoading] = useState(false);

  // Custom Category State
  const [showAddCategory, setShowAddCategory] = useState(false);
  const [newCatName, setNewCatName] = useState("");
  const [newCatDesc, setNewCatDesc] = useState("");

  // Agentic Pipeline States
  const [agentRuns, setAgentRuns] = useState<any[]>([]);
  const [triggeringAgent, setTriggeringAgent] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch all data
  const fetchData = async () => {
    try {
      const [txRes, catRes, insRes, accRes, runRes] = await Promise.all([
        fetch(`${API_BASE}/transactions`),
        fetch(`${API_BASE}/categories`),
        fetch(`${API_BASE}/analytics/insights`),
        fetch(`${API_BASE}/accounts`),
        fetch(`${API_BASE}/agent-runs`)
      ]);

      if (txRes.ok) setTransactions(await txRes.json());
      if (catRes.ok) setCategories(await catRes.json());
      if (insRes.ok) setInsights(await insRes.json());
      if (accRes.ok) setAccounts(await accRes.json());
      if (runRes.ok) setAgentRuns(await runRes.json());
    } catch (err) {
      console.error("Failed to connect to API:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    
    // Background polling for agent execution runs (every 5 seconds)
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/agent-runs`);
        if (res.ok) {
          setAgentRuns(await res.json());
        }
      } catch (err) {
        console.error("Failed to poll agent runs:", err);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, []);


  // Handle statement file upload
  const handleFileUpload = async (file: File) => {
    setUploading(true);
    setUploadResult(null);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        if (data.status === "parse_failed") {
          setAiConfirmModal({
            fileId: data.file_id,
            cost: data.estimated_cost_usd,
            filename: file.name
          });
        } else {
          setUploadResult({
            imported: data.transactions_imported,
            duplicates: data.duplicates_skipped
          });
          fetchData();
        }
      } else {
        alert(data.detail || "Ingestion parsing failed.");
      }
    } catch (err) {
      alert("Failed to connect to backend server.");
    } finally {
      setUploading(false);
    }
  };

  // Confirm and run AI parsing fallback
  const handleAIConfirm = async () => {
    if (!aiConfirmModal) return;
    setUploading(true);
    const fileId = aiConfirmModal.fileId;
    setAiConfirmModal(null);

    try {
      const res = await fetch(`${API_BASE}/upload/ai-confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: fileId })
      });
      const data = await res.json();
      if (res.ok) {
        setUploadResult({
          imported: data.transactions_imported,
          duplicates: data.duplicates_skipped
        });
        fetchData();
      } else {
        alert(data.detail || "AI statement parsing failed.");
      }
    } catch (err) {
      alert("Failed to connect to backend server.");
    } finally {
      setUploading(false);
    }
  };

  // Drag and drop handlers
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  // Create customized category
  const handleAddCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCatName.trim()) return;

    try {
      const res = await fetch(`${API_BASE}/categories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newCatName, description: newCatDesc })
      });
      if (res.ok) {
        setNewCatName("");
        setNewCatDesc("");
        setShowAddCategory(false);
        fetchData();
      } else {
        const err = await res.json();
        alert(err.detail);
      }
    } catch (err) {
      alert("Failed to save category.");
    }
  };

  // Apply Override Category (Manual Override & Rules Engine)
  const applyCategoryOverride = async (applyToAll: boolean) => {
    if (!overrideModal) return;
    try {
      const res = await fetch(`${API_BASE}/override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transaction_id: overrideModal.txId,
          category: overrideModal.newCategory,
          apply_to_all_matching: applyToAll
        })
      });
      if (res.ok) {
        setOverrideModal(null);
        setEditingTxId(null);
        fetchData();
      }
    } catch (err) {
      alert("Failed to override category.");
    }
  };

  // Fetch linking candidate list
  const fetchCandidates = async (txId: string) => {
    setCandidateLoading(true);
    setActiveLinkingTxId(txId);
    try {
      const res = await fetch(`${API_BASE}/transactions/link-candidates?transaction_id=${txId}`);
      if (res.ok) {
        setLinkCandidates(await res.json());
      } else {
        alert("Failed to load candidates.");
      }
    } catch (err) {
      console.error(err);
    } finally {
      setCandidateLoading(false);
    }
  };

  // Perform transaction linking
  const handleLink = async (txId1: string, txId2: string) => {
    try {
      const res = await fetch(`${API_BASE}/transactions/link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transaction_id_1: txId1,
          transaction_id_2: txId2
        })
      });
      if (res.ok) {
        setActiveLinkingTxId(null);
        setLinkCandidates([]);
        fetchData();
      } else {
        alert("Linking failed.");
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Perform transaction unlinking
  const handleUnlink = async (txId: string) => {
    if (!confirm("Are you sure you want to unlink these transactions?")) return;
    try {
      const res = await fetch(`${API_BASE}/transactions/unlink`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transaction_id: txId })
      });
      if (res.ok) {
        fetchData();
      } else {
        alert("Unlinking failed.");
      }
    } catch (err) {
      console.error(err);
    }
  };


  // Filter transactions for the selected account view
  const accountTransactions = transactions.filter(tx => {
    if (selectedAccount === "consolidated") return true;
    return tx.account_id === selectedAccount;
  });

  // Filter transactions to exclude linked / self-transfers for calculations/insights
  const filteredTxsForMetrics = accountTransactions.filter(tx => {
    if (selectedAccount === "consolidated") {
      // Exclude linked transactions and Self-Transfers from consolidated spend/income KPIs
      return !tx.linked_transaction_id && tx.category !== "Self-Transfers";
    }
    return true; // Keep all for specific statement views
  });

  // Financial calculations using metrics-filtered data
  const totalIncome = filteredTxsForMetrics
    .filter(tx => tx.amount > 0)
    .reduce((sum, tx) => sum + tx.amount, 0);

  const totalExpense = filteredTxsForMetrics
    .filter(tx => tx.amount < 0)
    .reduce((sum, tx) => sum + tx.amount, 0);

  const netBalanceChange = totalIncome + totalExpense;

  const savingsRate = totalIncome > 0 
    ? ((totalIncome - Math.abs(totalExpense)) / totalIncome) * 100 
    : 0;

  // Chart aggregation: Spend by Category (Always exclude Self-Transfers and linked transactions from Spend chart)
  const spendByCategoryData = Object.entries(
    accountTransactions
      .filter(tx => tx.amount < 0 && tx.category !== "Self-Transfers" && !tx.linked_transaction_id)
      .reduce((acc, tx) => {
        const cat = tx.category || "Others";
        acc[cat] = (acc[cat] || 0) + Math.abs(tx.amount);
        return acc;
      }, {} as Record<string, number>)
  ).map(([name, value]) => ({ name, value }));

  // Color mapping matching categories for UI charts
  const getCategoryColor = (cat: string) => {
    const colors: Record<string, string> = {
      "Online Cab Service": "#8b5cf6", // Purple
      "Investment": "#10b981",         // Green
      "Food and Drinks outside": "#f59e0b", // Orange
      "Online Food delivery": "#ef4444",    // Red
      "Online Grocery": "#ec4899",     // Pink
      "Grocery": "#06b6d4",            // Cyan
      "Bank Transfer": "#6b7280",      // Slate
      "Self-Transfers": "#3b82f6",     // Blue
      "Drinks": "#eab308",             // Yellow
      "Others": "#cbd5e1"              // Slate Light
    };
    return colors[cat] || "#6366f1";
  };

  // Chart aggregation: Monthly Trend
  const monthlyAggregates = Object.entries(
    filteredTxsForMetrics.reduce((acc, tx) => {
      const month = tx.date.substring(0, 7); // YYYY-MM
      if (!acc[month]) {
        acc[month] = { month, income: 0, expense: 0 };
      }
      if (tx.amount > 0) {
        acc[month].income += tx.amount;
      } else {
        acc[month].expense += Math.abs(tx.amount);
      }
      return acc;
    }, {} as Record<string, { month: string; income: number; expense: number }>)
  )
    .map(([_, v]) => ({
      ...v,
      savingsRate: v.income > 0 ? ((v.income - v.expense) / v.income) * 100 : 0
    }))
    .sort((a, b) => a.month.localeCompare(b.month));

  // Ledger sorting and search filtering
  const filteredTransactions = accountTransactions
    .filter(tx => {
      const matchesSearch = tx.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
                            (tx.category && tx.category.toLowerCase().includes(searchTerm.toLowerCase()));
      const matchesCategory = filterCategory === "all" || tx.category === filterCategory;
      return matchesSearch && matchesCategory;
    })
    .sort((a, b) => {
      let multiplier = sortOrder === "asc" ? 1 : -1;
      if (sortField === "date") {
        return a.date.localeCompare(b.date) * multiplier;
      } else {
        return (a.amount - b.amount) * multiplier;
      }
    });


  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 font-sans antialiased pb-12">
      {/* Top Header */}
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="p-2.5 bg-violet-600/20 text-violet-400 rounded-xl border border-violet-500/30">
              <TrendingUp className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white m-0 leading-none">FinIntel</h1>
              <span className="text-xs text-slate-400">Personal Finance Intelligence Dashboard</span>
            </div>
          </div>
          <div className="flex items-center space-x-4">
            <button 
              onClick={() => setShowAddCategory(true)}
              className="px-4 py-2 text-sm font-medium bg-slate-800 hover:bg-slate-700 text-white rounded-lg border border-slate-700 flex items-center gap-2 cursor-pointer transition-all"
            >
              <Plus className="h-4 w-4" /> Add Category
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="px-4 py-2 text-sm font-medium bg-violet-600 hover:bg-violet-500 text-white rounded-lg flex items-center gap-2 cursor-pointer transition-all shadow-lg shadow-violet-500/10"
            >
              <Upload className="h-4 w-4" /> Upload Statement
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 mt-8 space-y-8">
        
        {/* View Switcher Tabs */}
        <section className="bg-slate-800/20 p-1.5 rounded-xl border border-slate-800 flex items-center space-x-2 overflow-x-auto">
          <button
            onClick={() => setSelectedAccount("consolidated")}
            className={`px-4 py-2 text-sm font-semibold rounded-lg cursor-pointer transition-all whitespace-nowrap ${
              selectedAccount === "consolidated"
                ? "bg-violet-600 text-white shadow-md shadow-violet-600/10"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Consolidated View
          </button>
          <button
            onClick={() => setSelectedAccount("agentic")}
            className={`px-4 py-2 text-sm font-semibold rounded-lg cursor-pointer transition-all whitespace-nowrap ${
              selectedAccount === "agentic"
                ? "bg-violet-600 text-white shadow-md shadow-violet-600/10"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            🤖 Agent Pipeline
          </button>
          {accounts.map(acc => (
            <button
              key={acc}
              onClick={() => setSelectedAccount(acc)}
              className={`px-4 py-2 text-sm font-semibold rounded-lg cursor-pointer transition-all whitespace-nowrap ${
                selectedAccount === acc
                  ? "bg-violet-600 text-white shadow-md shadow-violet-600/10"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {acc}
            </button>
          ))}
        </section>

        {selectedAccount !== "agentic" && (
          <>
            {/* KPI Summaries */}
            <section className="grid grid-cols-1 md:grid-cols-4 gap-6">

          <div className="bg-slate-800/50 p-6 rounded-2xl border border-slate-800/80 shadow-md">
            <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider block">Net Balance Change</span>
            <div className="flex items-baseline gap-2 mt-2">
              <span className="text-2xl font-bold text-white">
                {netBalanceChange >= 0 ? "+" : ""}₹{netBalanceChange.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className={`text-xs font-semibold flex items-center gap-1 ${netBalanceChange >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {netBalanceChange >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                {netBalanceChange >= 0 ? "Gain" : "Loss"}
              </span>
            </div>
          </div>

          <div className="bg-slate-800/50 p-6 rounded-2xl border border-slate-800/80 shadow-md">
            <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider block">Total Inflow</span>
            <div className="flex items-baseline gap-2 mt-2">
              <span className="text-2xl font-bold text-emerald-400">
                ₹{totalIncome.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          <div className="bg-slate-800/50 p-6 rounded-2xl border border-slate-800/80 shadow-md">
            <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider block">Total Outflow</span>
            <div className="flex items-baseline gap-2 mt-2">
              <span className="text-2xl font-bold text-rose-400">
                -₹{Math.abs(totalExpense).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          <div className="bg-slate-800/50 p-6 rounded-2xl border border-slate-800/80 shadow-md">
            <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider block">Savings Rate</span>
            <div className="flex items-baseline gap-2 mt-2">
              <span className="text-2xl font-bold text-violet-400">
                {savingsRate.toFixed(1)}%
              </span>
              <span className="text-xs text-slate-400">of income saved</span>
            </div>
          </div>
        </section>

        {/* Secure Ingestion Upload Box */}
        {transactions.length === 0 && !loading && (
          <section 
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-3xl p-12 text-center cursor-pointer transition-all flex flex-col items-center justify-center ${
              dragActive 
                ? "border-violet-500 bg-violet-600/5" 
                : "border-slate-700 bg-slate-800/20 hover:bg-slate-800/30"
            }`}
            onClick={() => fileInputRef.current?.click()}
          >
            <input 
              type="file" 
              ref={fileInputRef}
              onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
              className="hidden" 
              accept=".pdf,.csv,.txt"
            />
            {uploading ? (
              <div className="flex flex-col items-center gap-3">
                <Loader2 className="h-10 w-10 text-violet-500 animate-spin" />
                <h3 className="text-lg font-semibold text-white">Analyzing statement details...</h3>
                <p className="text-sm text-slate-400">Scrubbing PII, parsing tables, and running AI categorization engine</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <div className="p-4 bg-violet-600/10 text-violet-400 rounded-2xl border border-violet-500/20 mb-2">
                  <Upload className="h-8 w-8" />
                </div>
                <h3 className="text-lg font-semibold text-white">Secure Statement Upload</h3>
                <p className="text-sm text-slate-400 max-w-md">
                  Drag and drop your bank PDF or CSV statements here. File stays in memory and is instantly discarded post-parsing.
                </p>
                <span className="text-xs text-slate-500 bg-slate-800 px-3 py-1 rounded-full mt-2">
                  PDF, CSV & TXT Statements Supported
                </span>
              </div>
            )}
          </section>
        )}

        {/* hidden input for header bar button upload */}
        <input 
          type="file" 
          ref={fileInputRef}
          onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
          className="hidden" 
          accept=".pdf,.csv,.txt"
        />

        {/* Upload Success Alert */}
        {uploadResult && (
          <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center justify-between text-slate-200">
            <div className="flex items-center gap-3">
              <CheckCircle className="h-5 w-5 text-emerald-400" />
              <div>
                <span className="font-semibold text-white">Statement Ingested Successfully!</span>
                <span className="text-sm text-slate-400 block">
                  Imported {uploadResult.imported} transactions. Skipped {uploadResult.duplicates} duplicates.
                </span>
              </div>
            </div>
            <button 
              onClick={() => setUploadResult(null)}
              className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700 cursor-pointer"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Behavioral Analytics AI Insights */}
        {transactions.length > 0 && (
          <section className="bg-slate-800/35 border border-slate-800/80 p-6 rounded-2xl">
            <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-violet-400" /> AI Behavioral Insights
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {insights.slice(0, 3).map((insight, idx) => (
                <div 
                  key={idx}
                  className={`p-5 rounded-xl border flex flex-col justify-between ${
                    insight.impact_level === "High Negative" 
                      ? "bg-rose-500/5 border-rose-500/20 text-rose-200" 
                      : insight.impact_level === "Medium Negative"
                      ? "bg-amber-500/5 border-amber-500/20 text-amber-200"
                      : "bg-slate-800/60 border-slate-700/50 text-slate-300"
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold text-sm text-white">{insight.category}</span>
                      <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded-full ${
                        insight.impact_level === "High Negative" 
                          ? "bg-rose-500/20 text-rose-400" 
                          : insight.impact_level === "Medium Negative"
                          ? "bg-amber-500/20 text-amber-400"
                          : "bg-slate-700 text-slate-400"
                      }`}>
                        {insight.impact_level} Impact
                      </span>
                    </div>
                    <p className="text-xs leading-relaxed mt-2 text-slate-300">
                      {insight.recommendation}
                    </p>
                  </div>
                  {insight.correlation < 0 && (
                    <div className="mt-4 pt-3 border-t border-slate-800/50 flex items-center justify-between text-[11px] text-slate-400">
                      <span>Correlation Index: <strong className="text-white">{(insight.correlation).toFixed(2)}</strong></span>
                      <span>Savings Elasticity: <strong className="text-white">+{insight.savings_rate_impact.toFixed(0)}%</strong></span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Charts Grid */}
        {transactions.length > 0 && (
          <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Chart 1: Expenditure vs Category */}
            <div className="bg-slate-800/40 p-6 rounded-2xl border border-slate-800/80">
              <h3 className="text-md font-semibold text-white mb-4">Total Spending vs Category</h3>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={spendByCategoryData}>
                    <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} tickLine={false} />
                    <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", color: "#f8fafc" }}
                      formatter={(val) => [`₹${Number(val).toLocaleString()}`, "Amount"]}
                    />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                      {spendByCategoryData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={getCategoryColor(entry.name)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Chart 2: Time-series Spend Trend Line */}
            <div className="bg-slate-800/40 p-6 rounded-2xl border border-slate-800/80">
              <h3 className="text-md font-semibold text-white mb-4">Monthly Spend Trend Line</h3>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={monthlyAggregates}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="month" stroke="#94a3b8" fontSize={11} />
                    <YAxis stroke="#94a3b8" fontSize={11} />
                    <Tooltip contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", color: "#f8fafc" }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="expense" name="Outflow (₹)" stroke="#ef4444" strokeWidth={2} activeDot={{ r: 6 }} />
                    <Line type="monotone" dataKey="income" name="Inflow (₹)" stroke="#10b981" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </section>
        )}

        {/* Transaction Ledger Table */}
        {transactions.length > 0 && (
          <section className="bg-slate-800/40 border border-slate-800/80 rounded-2xl overflow-hidden">
            <div className="p-6 border-b border-slate-800 flex flex-col md:flex-row items-center justify-between gap-4">
              <h2 className="text-md font-semibold text-white m-0">Transaction Ledger</h2>
              
              {/* Filter controls */}
              <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
                <div className="relative flex-1 md:flex-initial">
                  <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search descriptions..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full md:w-64 pl-9 pr-4 py-2 text-sm bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:border-violet-500"
                  />
                </div>
                
                <select
                  value={filterCategory}
                  onChange={(e) => setFilterCategory(e.target.value)}
                  className="px-3 py-2 text-sm bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-violet-500"
                >
                  <option value="all">All Categories</option>
                  {categories.map(c => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 text-xs font-semibold uppercase tracking-wider bg-slate-900/30">
                    <th className="px-6 py-4">Date</th>
                    <th className="px-6 py-4">Account</th>
                    <th className="px-6 py-4">Description</th>
                    <th className="px-6 py-4">Category</th>
                    <th className="px-6 py-4">Linking</th>
                    <th className="px-6 py-4 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50 text-sm">
                  {filteredTransactions.map((tx) => (
                    <tr key={tx.id} className="hover:bg-slate-800/20 transition-colors">
                      <td className="px-6 py-4 text-slate-300 font-medium whitespace-nowrap">
                        {tx.date}
                      </td>
                      <td className="px-6 py-4 text-slate-400 font-semibold whitespace-nowrap">
                        {tx.account_id || "General"}
                      </td>
                      <td className="px-6 py-4 text-white font-medium max-w-xs truncate" title={tx.description}>
                        {tx.description}
                      </td>
                      <td className="px-6 py-3 whitespace-nowrap">
                        {editingTxId === tx.id ? (
                          <div className="flex items-center gap-1.5">
                            <select
                              value={tx.category || "Others"}
                              onChange={(e) => {
                                const newCat = e.target.value;
                                if (newCat !== tx.category) {
                                  setOverrideModal({
                                    txId: tx.id,
                                    description: tx.description,
                                    newCategory: newCat
                                  });
                                } else {
                                  setEditingTxId(null);
                                }
                              }}
                              className="px-2 py-1 text-xs bg-slate-900 border border-slate-700 rounded text-white focus:outline-none focus:border-violet-500"
                            >
                              {categories.map(c => (
                                <option key={c.name} value={c.name}>{c.name}</option>
                              ))}
                            </select>
                            <button 
                              onClick={() => setEditingTxId(null)}
                              className="text-[10px] text-slate-400 hover:text-slate-200 cursor-pointer"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span 
                              className="inline-flex items-center px-2.5 py-1.5 rounded-full text-xs font-semibold"
                              style={{ 
                                backgroundColor: `${getCategoryColor(tx.category || "Others")}20`, 
                                color: getCategoryColor(tx.category || "Others") 
                              }}
                            >
                              {tx.category || "Others"}
                            </span>
                            <button
                              onClick={() => setEditingTxId(tx.id)}
                              className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-slate-300 cursor-pointer hover:bg-slate-800 rounded transition-all"
                              style={{ opacity: 1 }} // Force visibility for easy override click
                            >
                              <Edit2 className="h-3 w-3" />
                            </button>
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-3 whitespace-nowrap">
                        {tx.linked_transaction_id ? (
                          <div className="flex items-center gap-2">
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                              🔗 Linked
                            </span>
                            <button
                              onClick={() => handleUnlink(tx.id)}
                              className="text-xs text-rose-450 hover:text-rose-350 cursor-pointer bg-slate-800 hover:bg-slate-750 px-2 py-1 rounded border border-slate-700 font-semibold"
                            >
                              Unlink
                            </button>
                          </div>
                        ) : activeLinkingTxId === tx.id ? (
                          <div className="flex items-center gap-2">
                            {candidateLoading ? (
                              <span className="text-xs text-slate-400 animate-pulse">Loading candidates...</span>
                            ) : linkCandidates.length > 0 ? (
                              <select
                                onChange={(e) => {
                                  if (e.target.value) {
                                    handleLink(tx.id, e.target.value);
                                  }
                                }}
                                className="px-2 py-1 text-xs bg-slate-900 border border-slate-700 rounded text-white focus:outline-none focus:border-violet-500 max-w-[180px]"
                                defaultValue=""
                              >
                                <option value="" disabled>Select partner...</option>
                                {linkCandidates.map(c => (
                                  <option key={c.id} value={c.id}>
                                    {c.date} - {c.account_id} - ₹{Math.abs(c.amount)}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <span className="text-xs text-rose-400 font-medium">No candidates found</span>
                            )}
                            <button
                              onClick={() => {
                                setActiveLinkingTxId(null);
                                setLinkCandidates([]);
                              }}
                              className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => fetchCandidates(tx.id)}
                            className="px-2.5 py-1 text-xs font-semibold bg-slate-800 hover:bg-slate-750 text-slate-300 border border-slate-700 rounded-lg cursor-pointer transition-all"
                          >
                            Link
                          </button>
                        )}
                      </td>
                      <td className={`px-6 py-4 text-right font-semibold whitespace-nowrap ${tx.amount > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {tx.amount > 0 ? "+" : ""}₹{tx.amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                    </tr>
                  ))}
                  {filteredTransactions.length === 0 && (
                    <tr>
                      <td colSpan={6} className="text-center py-8 text-slate-400">
                        No transactions found matching your criteria.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}
          </>
        )}

        {/* Agentic Pipeline Dashboard */}
        {selectedAccount === "agentic" && (
          <section className="space-y-6">
            <div className="bg-slate-800/40 p-6 rounded-2xl border border-slate-800/80 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  🤖 Autonomous Agent Pipeline
                </h2>
                <p className="text-sm text-slate-400 mt-1">
                  Monitor trigger scans, orchestrator workflows, and super-agent logs. Place bank statement files in <code className="text-violet-400 bg-slate-900 px-1.5 py-0.5 rounded font-mono">backend/statements_to_process/</code> or <code className="text-violet-400 bg-slate-900 px-1.5 py-0.5 rounded font-mono">backend/email_inbox/</code> to trigger autonomously.
                </p>
              </div>
              <button
                onClick={async () => {
                  setTriggeringAgent(true);
                  try {
                    const res = await fetch(`${API_BASE}/agent-runs/trigger`, { method: "POST" });
                    if (res.ok) {
                      const data = await res.json();
                      alert(data.message);
                      fetchData();
                    } else {
                      alert("Trigger failed.");
                    }
                  } catch (err) {
                    alert("Error connecting to backend trigger.");
                  } finally {
                    setTriggeringAgent(false);
                  }
                }}
                disabled={triggeringAgent}
                className="px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:bg-violet-850 disabled:cursor-not-allowed text-white rounded-lg text-sm font-semibold flex items-center gap-2 cursor-pointer transition-all shadow-lg shadow-violet-500/10 whitespace-nowrap"
              >
                {triggeringAgent ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Scanning...
                  </>
                ) : (
                  "Trigger Manual Scan"
                )}
              </button>
            </div>

            <div className="space-y-4">
              {agentRuns.length === 0 ? (
                <div className="bg-slate-800/40 border border-slate-800/80 p-12 rounded-2xl text-center text-slate-400">
                  No agent execution logs found. Drop statement files in the monitored directories or click Trigger Manual Scan to start.
                </div>
              ) : (
                agentRuns.map((run) => {
                  let parsedLogs = [];
                  try {
                    parsedLogs = JSON.parse(run.log_output);
                  } catch (e) {
                    parsedLogs = [run.log_output];
                  }

                  const getStatusBadge = (status: string) => {
                    const styles: Record<string, string> = {
                      completed: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
                      failed: "bg-rose-500/15 text-rose-400 border-rose-500/25",
                      started: "bg-blue-500/15 text-blue-400 border-blue-500/25",
                      parsing: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
                      mapping: "bg-violet-500/15 text-violet-400 border-violet-500/25",
                      analyzing: "bg-cyan-500/15 text-cyan-400 border-cyan-500/25",
                      frontend: "bg-pink-500/15 text-pink-400 border-pink-500/25"
                    };
                    return (
                      <span className={`px-2.5 py-0.5 text-xs font-semibold border rounded-full capitalize ${styles[status] || "bg-slate-800 text-slate-350"}`}>
                        {status}
                      </span>
                    );
                  };

                  return (
                    <div key={run.id} className="bg-slate-800/20 border border-slate-800/80 rounded-2xl overflow-hidden shadow-sm hover:border-slate-700/60 transition-all">
                      <div className="p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/10">
                        <div className="space-y-1">
                          <div className="flex items-center gap-3">
                            <span className="font-semibold text-white text-sm">Run ID: {run.id.substring(0, 8)}...</span>
                            {getStatusBadge(run.status)}
                          </div>
                          <div className="text-xs text-slate-400">
                            Source: <strong className="text-slate-300">{run.statement_source}</strong> • {new Date(run.timestamp).toLocaleString()}
                          </div>
                        </div>
                      </div>

                      {run.error_message && (
                        <div className="mx-5 mb-4 p-4 bg-rose-500/5 border border-rose-500/20 rounded-xl text-xs text-rose-350 font-mono whitespace-pre-wrap">
                          <strong>Error Summary:</strong><br />
                          {run.error_message}
                        </div>
                      )}

                      <div className="border-t border-slate-800 bg-slate-950 p-5">
                        <h4 className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-3">Execution Console Logs</h4>
                        <div className="max-h-60 overflow-y-auto space-y-1 font-mono text-[11px] leading-relaxed text-slate-300 select-text">
                          {parsedLogs.map((logLine: string, idx: number) => (
                            <div key={idx} className="hover:bg-slate-900/40 px-1 py-0.5 rounded transition-all">
                              {logLine}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </section>
        )}
      </main>

      {/* Manual Override Confirmation Dialog / Modal */}
      {overrideModal && (
        <div className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-md w-full space-y-4 shadow-xl">
            <h3 className="text-lg font-bold text-white">Save Override Rule?</h3>
            <p className="text-sm text-slate-300">
              You corrected the category of <strong className="text-violet-400">"{overrideModal.description}"</strong> to <strong className="text-emerald-400">"{overrideModal.newCategory}"</strong>.
            </p>
            <p className="text-xs text-slate-400 leading-relaxed">
              Would you like the engine to create a categorization rule pattern to apply this match automatically to all future and matching historical transactions?
            </p>
            <div className="flex flex-col gap-2.5 pt-2">
              <button
                onClick={() => applyCategoryOverride(true)}
                className="w-full py-2.5 text-sm font-medium bg-violet-600 hover:bg-violet-500 text-white rounded-lg cursor-pointer transition-all"
              >
                Yes, Remember this rule (Apply to All Matching)
              </button>
              <button
                onClick={() => applyCategoryOverride(false)}
                className="w-full py-2.5 text-sm font-medium bg-slate-800 hover:bg-slate-700 text-white rounded-lg border border-slate-700 cursor-pointer transition-all"
              >
                No, Apply only to this transaction
              </button>
              <button
                onClick={() => setOverrideModal(null)}
                className="w-full py-2 text-xs font-semibold text-slate-400 hover:text-slate-200 cursor-pointer transition-all"
              >
                Cancel Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Custom Category Dialog */}
      {showAddCategory && (
        <div className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <form onSubmit={handleAddCategory} className="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-md w-full space-y-4 shadow-xl">
            <h3 className="text-lg font-bold text-white">Add Custom Category</h3>
            
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">Category Name</label>
              <input
                type="text"
                required
                placeholder="e.g. Travel, Gym Membership..."
                value={newCatName}
                onChange={(e) => setNewCatName(e.target.value)}
                className="w-full px-3.5 py-2 text-sm bg-slate-950 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-violet-500"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">Description (Optional)</label>
              <textarea
                placeholder="Brief category context..."
                value={newCatDesc}
                onChange={(e) => setNewCatDesc(e.target.value)}
                rows={2}
                className="w-full px-3.5 py-2 text-sm bg-slate-950 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-violet-500 resize-none"
              />
            </div>

            <div className="flex gap-3 pt-2">
              <button
                type="submit"
                className="flex-1 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm font-medium cursor-pointer transition-all"
              >
                Add Category
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowAddCategory(false);
                  setNewCatName("");
                  setNewCatDesc("");
                }}
                className="flex-1 py-2 bg-slate-850 hover:bg-slate-800 text-slate-300 rounded-lg text-sm font-medium border border-slate-700 cursor-pointer transition-all"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* AI Parsing Confirmation Dialog / Modal */}
      {aiConfirmModal && (
        <div className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-md w-full space-y-4 shadow-xl">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" /> AI Parsing Approval
            </h3>
            <p className="text-sm text-slate-300">
              The standard parser could not read the layout of <strong className="text-violet-400">"{aiConfirmModal.filename}"</strong>.
            </p>
            <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-400">Analysis Method:</span>
                <span className="text-amber-400 font-semibold">Gemini AI Parser</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Estimated Cost:</span>
                <span className="text-white font-semibold">${aiConfirmModal.cost.toFixed(6)} USD</span>
              </div>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              Enabling AI parsing submits the statement text to the LLM to extract transaction rows. You will be billed standard Gemini tokens.
            </p>
            <div className="flex flex-col gap-2.5 pt-2">
              <button
                onClick={handleAIConfirm}
                className="w-full py-2.5 text-sm font-medium bg-amber-600 hover:bg-amber-500 text-white rounded-lg cursor-pointer transition-all flex items-center justify-center gap-2 shadow-lg shadow-amber-600/10"
              >
                Approve and Ingest
              </button>
              <button
                onClick={() => setAiConfirmModal(null)}
                className="w-full py-2.5 text-sm font-medium bg-slate-850 hover:bg-slate-800 text-slate-300 rounded-lg border border-slate-700 cursor-pointer transition-all"
              >
                Cancel Ingestion
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
