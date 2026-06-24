import React, { useState, useEffect, useRef } from "react";
import { 
  Upload, ArrowDownRight, ArrowUpRight, 
  TrendingUp, AlertTriangle, CheckCircle, 
  Plus, Edit2, Search, Loader2,
  ChevronUp, ChevronDown, ArrowUpDown, SlidersHorizontal, RotateCcw, X
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
  ai_rate_limited?: boolean;
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

  const [parserCreatorModal, setParserCreatorModal] = useState<{
    fileId: string;
    filename: string;
    filePath: string;
    textPreview: string;
  } | null>(null);
  const [activeParserRunId, setActiveParserRunId] = useState<string | null>(null);
  const [showUpdatePrompt, setShowUpdatePrompt] = useState(false);

  // Search & Filter States
  const [searchTerm, setSearchTerm] = useState("");
  const [filterCategory, setFilterCategory] = useState("all");
  const [sortField, setSortField] = useState<"date" | "amount" | "description" | "category" | "account_id">("date");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [filterTxType, setFilterTxType] = useState<"all" | "inflow" | "outflow">("all");
  const [filterDateRange, setFilterDateRange] = useState<"all" | "last30" | "thisMonth" | "lastMonth" | "custom">("all");
  const [customStartDate, setCustomStartDate] = useState<string>("");
  const [customEndDate, setCustomEndDate] = useState<string>("");
  const [minAmount, setMinAmount] = useState<string>("");
  const [maxAmount, setMaxAmount] = useState<string>("");
  const [showAdvancedFilters, setShowAdvancedFilters] = useState<boolean>(false);

  // Sorting Handler
  const handleSort = (field: typeof sortField) => {
    if (sortField === field) {
      setSortOrder(prev => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      if (field === "date" || field === "amount") {
        setSortOrder("desc");
      } else {
        setSortOrder("asc");
      }
    }
  };


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

  // AI Status & Rate Limit States
  const [aiStatus, setAiStatus] = useState<{ is_rate_limited: boolean; seconds_remaining: number }>({
    is_rate_limited: false,
    seconds_remaining: 0
  });
  const [showOnlyRateLimited, setShowOnlyRateLimited] = useState(false);
  const [selectedTxIds, setSelectedTxIds] = useState<Record<string, boolean>>({});
  const [reclassifying, setReclassifying] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Loading & Progress Indicator States
  const [activeRequests, setActiveRequests] = useState(0);
  const [isMutating, setIsMutating] = useState(false);
  const [mutationMsg, setMutationMsg] = useState("");
  const [progress, setProgress] = useState(0);
  const [progressBarVisible, setProgressBarVisible] = useState(false);

  // Filter status & reset helpers
  const isAnyFilterActive = 
    searchTerm !== "" || 
    filterCategory !== "all" || 
    filterTxType !== "all" || 
    filterDateRange !== "all" || 
    customStartDate !== "" || 
    customEndDate !== "" || 
    minAmount !== "" || 
    maxAmount !== "" || 
    showOnlyRateLimited === true;

  const handleResetFilters = () => {
    setSearchTerm("");
    setFilterCategory("all");
    setFilterTxType("all");
    setFilterDateRange("all");
    setCustomStartDate("");
    setCustomEndDate("");
    setMinAmount("");
    setMaxAmount("");
    setShowOnlyRateLimited(false);
  };

  useEffect(() => {
    let interval: any;
    if (activeRequests > 0) {
      setProgressBarVisible(true);
      setProgress(10);
      interval = setInterval(() => {
        setProgress(prev => {
          if (prev < 70) return prev + 10;
          if (prev < 88) return prev + 2;
          if (prev < 95) return prev + 0.5;
          return prev;
        });
      }, 200);
    } else {
      setProgress(100);
      const timeout = setTimeout(() => {
        setProgressBarVisible(false);
        setProgress(0);
      }, 400);
      return () => clearTimeout(timeout);
    }
    return () => clearInterval(interval);
  }, [activeRequests]);


  // Fetch all data
  const fetchData = async () => {
    setActiveRequests(prev => prev + 1);
    try {
      const [txRes, catRes, insRes, accRes, runRes, statusRes] = await Promise.all([
        fetch(`${API_BASE}/transactions`),
        fetch(`${API_BASE}/categories`),
        fetch(`${API_BASE}/analytics/insights`),
        fetch(`${API_BASE}/accounts`),
        fetch(`${API_BASE}/agent-runs`),
        fetch(`${API_BASE}/ai-status`)
      ]);

      if (txRes.ok) setTransactions(await txRes.json());
      if (catRes.ok) setCategories(await catRes.json());
      if (insRes.ok) setInsights(await insRes.json());
      if (accRes.ok) setAccounts(await accRes.json());
      if (runRes.ok) setAgentRuns(await runRes.json());
      if (statusRes.ok) setAiStatus(await statusRes.json());
    } catch (err) {
      console.error("Failed to connect to API:", err);
    } finally {
      setActiveRequests(prev => Math.max(0, prev - 1));
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    
    // Background polling for agent execution runs (every 5 seconds)
    const runInterval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/agent-runs`);
        if (res.ok) {
          setAgentRuns(await res.json());
        }
      } catch (err) {
        console.error("Failed to poll agent runs:", err);
      }
    }, 5000);

    // Background polling for AI rate limit status (every 10 seconds)
    const statusInterval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/ai-status`);
        if (res.ok) {
          setAiStatus(await res.json());
        }
      } catch (err) {
        console.error("Failed to poll AI status:", err);
      }
    }, 10000);

    return () => {
      clearInterval(runInterval);
      clearInterval(statusInterval);
    };
  }, []);

  useEffect(() => {
    if (activeParserRunId) {
      const activeRun = agentRuns.find(r => r.id === activeParserRunId);
      if (activeRun) {
        if (activeRun.status === "completed") {
          setActiveParserRunId(null);
          setShowUpdatePrompt(true);
        } else if (activeRun.status === "failed") {
          setActiveParserRunId(null);
          alert("Autonomous parser creator run failed. Please check the logs in the run panel.");
        }
      }
    }
  }, [agentRuns, activeParserRunId]);


  // Handle statement file upload
  const handleFileUpload = async (file: File) => {
    setUploading(true);
    setUploadResult(null);
    setIsMutating(true);
    setMutationMsg("Uploading and analyzing bank statement...");
    setActiveRequests(prev => prev + 1);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        if (data.status === "new_parser_required") {
          setParserCreatorModal({
            fileId: data.file_id,
            filename: file.name,
            filePath: data.file_path,
            textPreview: data.text_preview
          });
        } else if (data.status === "parse_failed") {
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
          await fetchData();
        }
      } else {
        alert(data.detail || "Ingestion parsing failed.");
      }
    } catch (err) {
      alert("Failed to connect to backend server.");
    } finally {
      setUploading(false);
      setIsMutating(false);
      setMutationMsg("");
      setActiveRequests(prev => Math.max(0, prev - 1));
    }
  };

  // Confirm and run AI parsing fallback
  const handleAIConfirm = async () => {
    if (!aiConfirmModal) return;
    setUploading(true);
    setIsMutating(true);
    setMutationMsg("Processing bank statement with Gemini AI Parser...");
    setActiveRequests(prev => prev + 1);
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
        await fetchData();
      } else {
        alert(data.detail || "AI statement parsing failed.");
      }
    } catch (err) {
      alert("Failed to connect to backend server.");
    } finally {
      setUploading(false);
      setIsMutating(false);
      setMutationMsg("");
      setActiveRequests(prev => Math.max(0, prev - 1));
    }
  };

  // Submit build parser request
  const handleBuildParser = async () => {
    if (!parserCreatorModal) return;
    setUploading(true);
    setIsMutating(true);
    setMutationMsg("Initiating autonomous parser creator agent...");
    setActiveRequests(prev => prev + 1);
    
    const { fileId, filePath } = parserCreatorModal;
    setParserCreatorModal(null);
    
    try {
      const res = await fetch(`${API_BASE}/upload/build-parser`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: fileId, file_path: filePath })
      });
      const data = await res.json();
      if (res.ok && data.run_id) {
        setActiveParserRunId(data.run_id);
      } else {
        alert(data.detail || "Failed to start parser builder.");
      }
    } catch (err) {
      alert("Failed to connect to backend server.");
    } finally {
      setUploading(false);
      setIsMutating(false);
      setMutationMsg("");
      setActiveRequests(prev => Math.max(0, prev - 1));
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
    setIsMutating(true);
    setMutationMsg("Adding custom category...");
    setActiveRequests(prev => prev + 1);

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
        await fetchData();
      } else {
        const err = await res.json();
        alert(err.detail);
      }
    } catch (err) {
      alert("Failed to save category.");
    } finally {
      setIsMutating(false);
      setMutationMsg("");
      setActiveRequests(prev => Math.max(0, prev - 1));
    }
  };

  // Apply Override Category (Manual Override & Rules Engine)
  const applyCategoryOverride = async (applyToAll: boolean) => {
    if (!overrideModal) return;
    setIsMutating(true);
    setMutationMsg(
      applyToAll 
        ? "Applying rule to all matching transactions..." 
        : "Applying manual category override..."
    );
    setActiveRequests(prev => prev + 1);
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
        await fetchData();
      }
    } catch (err) {
      alert("Failed to override category.");
    } finally {
      setIsMutating(false);
      setMutationMsg("");
      setActiveRequests(prev => Math.max(0, prev - 1));
    }
  };

  // Fetch linking candidate list
  const fetchCandidates = async (txId: string) => {
    setCandidateLoading(true);
    setActiveLinkingTxId(txId);
    setActiveRequests(prev => prev + 1);
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
      setActiveRequests(prev => Math.max(0, prev - 1));
    }
  };

  // Perform transaction linking
  const handleLink = async (txId1: string, txId2: string) => {
    setIsMutating(true);
    setMutationMsg("Linking transactions as self-transfer...");
    setActiveRequests(prev => prev + 1);
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
        await fetchData();
      } else {
        alert("Linking failed.");
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsMutating(false);
      setMutationMsg("");
      setActiveRequests(prev => Math.max(0, prev - 1));
    }
  };

  // Perform transaction unlinking
  const handleUnlink = async (txId: string) => {
    if (!confirm("Are you sure you want to unlink these transactions?")) return;
    setIsMutating(true);
    setMutationMsg("Unlinking transactions...");
    setActiveRequests(prev => prev + 1);
    try {
      const res = await fetch(`${API_BASE}/transactions/unlink`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transaction_id: txId })
      });
      if (res.ok) {
        await fetchData();
      } else {
        alert("Unlinking failed.");
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsMutating(false);
      setMutationMsg("");
      setActiveRequests(prev => Math.max(0, prev - 1));
    }
  };

  // Perform force re-classification
  const handleForceReclassify = async () => {
    const ids = Object.keys(selectedTxIds).filter(id => selectedTxIds[id]);
    if (ids.length === 0) return;
    setReclassifying(true);
    setIsMutating(true);
    setMutationMsg(`Reclassifying ${ids.length} selected transactions...`);
    setActiveRequests(prev => prev + 1);
    try {
      const res = await fetch(`${API_BASE}/transactions/reclassify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transaction_ids: ids })
      });
      const data = await res.json();
      if (res.ok) {
        setSelectedTxIds({});
        await fetchData();
      } else {
        alert(data.detail || "Reclassification failed.");
      }
    } catch (err) {
      alert("Failed to connect to backend for reclassification.");
    } finally {
      setReclassifying(false);
      setIsMutating(false);
      setMutationMsg("");
      setActiveRequests(prev => Math.max(0, prev - 1));
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
      const matchesRateLimit = !showOnlyRateLimited || tx.ai_rate_limited;
      
      // Transaction Type matching
      const matchesTxType = 
        filterTxType === "all" ||
        (filterTxType === "inflow" && tx.amount > 0) ||
        (filterTxType === "outflow" && tx.amount < 0);
        
      // Date Range matching
      let matchesDate = true;
      if (filterDateRange === "last30") {
        const limitDate = new Date();
        limitDate.setDate(limitDate.getDate() - 30);
        const limitStr = limitDate.toISOString().split('T')[0];
        matchesDate = tx.date >= limitStr;
      } else if (filterDateRange === "thisMonth") {
        const currentPrefix = new Date().toISOString().substring(0, 7);
        matchesDate = tx.date.startsWith(currentPrefix);
      } else if (filterDateRange === "lastMonth") {
        const d = new Date();
        d.setMonth(d.getMonth() - 1);
        const lastMonthPrefix = d.toISOString().substring(0, 7);
        matchesDate = tx.date.startsWith(lastMonthPrefix);
      } else if (filterDateRange === "custom") {
        const matchesStart = !customStartDate || tx.date >= customStartDate;
        const matchesEnd = !customEndDate || tx.date <= customEndDate;
        matchesDate = matchesStart && matchesEnd;
      }
      
      // Amount Range matching
      const absAmt = Math.abs(tx.amount);
      const minVal = parseFloat(minAmount);
      const maxVal = parseFloat(maxAmount);
      const matchesMin = isNaN(minVal) || absAmt >= minVal;
      const matchesMax = isNaN(maxVal) || absAmt <= maxVal;
      const matchesAmount = matchesMin && matchesMax;

      return matchesSearch && matchesCategory && matchesRateLimit && matchesTxType && matchesDate && matchesAmount;
    })
    .sort((a, b) => {
      let multiplier = sortOrder === "asc" ? 1 : -1;
      if (sortField === "amount") {
        return (a.amount - b.amount) * multiplier;
      } else if (sortField === "date") {
        return a.date.localeCompare(b.date) * multiplier;
      } else {
        const valA = a[sortField] || "";
        const valB = b[sortField] || "";
        return valA.localeCompare(valB) * multiplier;
      }
    });
  // Helper to render sortable table headers
  const renderSortHeader = (label: string, field: typeof sortField, alignRight: boolean = false) => {
    const isActive = sortField === field;
    return (
      <th 
        className={`px-6 py-4 select-none cursor-pointer group hover:bg-slate-800/40 transition-colors ${alignRight ? 'text-right' : ''}`}
        onClick={() => handleSort(field)}
      >
        <div className={`flex items-center gap-1 ${alignRight ? 'justify-end' : ''}`}>
          <span>{label}</span>
          <span>
            {isActive ? (
              sortOrder === "asc" ? (
                <ChevronUp className="h-3.5 w-3.5 text-violet-400 inline-block align-text-bottom ml-0.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5 text-violet-400 inline-block align-text-bottom ml-0.5" />
              )
            ) : (
              <ArrowUpDown className="h-3.5 w-3.5 text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity inline-block align-text-bottom ml-0.5" />
            )}
          </span>
        </div>
      </th>
    );
  };


  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 font-sans antialiased pb-12">
      {/* Sleek Top-of-Screen Progress Bar */}
      {progressBarVisible && (
        <div 
          className="fixed top-0 left-0 right-0 h-[3px] z-[9999] transition-opacity duration-300 pointer-events-none"
          style={{ opacity: progress === 100 ? 0 : 1 }}
        >
          <div 
            className="h-full bg-gradient-to-r from-violet-500 via-purple-500 to-pink-500 transition-all duration-300 ease-out shadow-[0_0_10px_rgba(139,92,246,0.5)]"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {/* Premium Glassmorphic Processing Overlay */}
      {isMutating && (
        <div className="fixed inset-0 bg-slate-950/60 backdrop-blur-md flex items-center justify-center z-[9998] animate-fade-in">
          <div className="bg-slate-900/90 border border-slate-800 p-8 rounded-3xl max-w-sm w-full flex flex-col items-center text-center space-y-5 shadow-2xl shadow-violet-950/20">
            <div className="relative">
              <div className="absolute inset-0 rounded-full bg-violet-600/10 blur-xl animate-pulse"></div>
              <div className="p-4 bg-violet-600/10 text-violet-400 rounded-2xl border border-violet-500/20 relative animate-spin duration-1000">
                <Loader2 className="h-8 w-8 animate-spin" />
              </div>
            </div>
            <div className="space-y-2">
              <h3 className="text-lg font-bold text-white">Processing Request</h3>
              <p className="text-sm text-slate-400 font-medium">
                {mutationMsg || "Please wait while we update your dashboard..."}
              </p>
            </div>
            <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden relative">
              <div className="absolute top-0 bottom-0 left-0 bg-gradient-to-r from-violet-500 to-pink-500 w-1/2 rounded-full animate-shimmer"></div>
            </div>
          </div>
        </div>
      )}
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
        {aiStatus.is_rate_limited && (
          <div className="p-4 bg-amber-500/10 border border-amber-500/30 text-amber-200 rounded-xl flex items-center justify-between shadow-lg shadow-amber-500/5 animate-pulse">
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-400 font-bold" />
              <div>
                <span className="font-semibold text-white">AI Engine Rate-Limited</span>
                <span className="text-sm text-slate-400 block mt-0.5">
                  AI categorization and conversational insights are temporarily paused to protect API limits. Local rules and vector search remain operational. Resuming in {aiStatus.seconds_remaining} seconds.
                </span>
              </div>
            </div>
          </div>
        )}
        
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
            <div className="p-6 border-b border-slate-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
              <div className="flex items-center gap-3 w-full md:w-auto justify-between md:justify-start">
                <h2 className="text-md font-semibold text-white m-0">Transaction Ledger</h2>
                {Object.values(selectedTxIds).some(Boolean) && (
                  <button
                    onClick={handleForceReclassify}
                    disabled={reclassifying}
                    className="px-3 py-1.5 text-xs bg-violet-600 hover:bg-violet-500 disabled:bg-slate-850 disabled:text-slate-500 disabled:cursor-not-allowed text-white rounded-lg font-semibold flex items-center gap-2 cursor-pointer transition-all shadow-lg shadow-violet-500/10"
                  >
                    {reclassifying ? (
                      <>
                        <Loader2 className="h-3 w-3 animate-spin" /> Reclassifying...
                      </>
                    ) : (
                      `Reclassify Selected (${Object.values(selectedTxIds).filter(Boolean).length})`
                    )}
                  </button>
                )}
              </div>
              
              {/* Primary Filter controls */}
              <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
                <div className="relative flex-1 md:flex-initial">
                  <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search descriptions..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full md:w-64 pl-9 pr-8 py-2 text-sm bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-450 focus:outline-none focus:border-violet-500 transition-all"
                  />
                  {searchTerm && (
                    <button
                      onClick={() => setSearchTerm("")}
                      className="absolute right-2.5 top-2.5 p-0.5 text-slate-400 hover:text-white rounded-md hover:bg-slate-800 transition-colors cursor-pointer"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>

                <select
                  value={filterCategory}
                  onChange={(e) => setFilterCategory(e.target.value)}
                  className="px-3.5 py-2 text-sm bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-violet-500 transition-all cursor-pointer"
                >
                  <option value="all">All Categories</option>
                  {categories.map(c => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>

                <select
                  value={filterTxType}
                  onChange={(e) => setFilterTxType(e.target.value as any)}
                  className="px-3.5 py-2 text-sm bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-violet-500 transition-all cursor-pointer"
                >
                  <option value="all">All Types</option>
                  <option value="inflow">Inflows Only</option>
                  <option value="outflow">Outflows Only</option>
                </select>

                <button
                  onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
                  className={`px-3.5 py-2 text-sm border rounded-lg transition-all cursor-pointer flex items-center gap-2 font-medium ${
                    showAdvancedFilters || filterDateRange !== "all" || minAmount !== "" || maxAmount !== "" || showOnlyRateLimited
                      ? "bg-violet-650/20 border-violet-500 text-violet-300"
                      : "bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <SlidersHorizontal className="h-4 w-4" />
                  <span>Filters</span>
                  {(filterDateRange !== "all" || minAmount !== "" || maxAmount !== "" || showOnlyRateLimited) && (
                    <span className="w-2 h-2 rounded-full bg-violet-400 animate-pulse"></span>
                  )}
                </button>

                {isAnyFilterActive && (
                  <button
                    onClick={handleResetFilters}
                    className="px-3.5 py-2 text-sm border border-slate-705 bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white rounded-lg transition-all cursor-pointer flex items-center gap-1.5 font-medium"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    <span>Reset</span>
                  </button>
                )}
              </div>
            </div>

            {/* Advanced Filters Panel */}
            {showAdvancedFilters && (
              <div className="px-6 pb-6 pt-2 border-b border-slate-800 bg-slate-900/10 grid grid-cols-1 md:grid-cols-3 gap-6 animate-fade-in">
                {/* Date Filter Column */}
                <div className="space-y-2">
                  <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Date Range</label>
                  <div className="flex flex-col gap-2">
                    <select
                      value={filterDateRange}
                      onChange={(e) => {
                        setFilterDateRange(e.target.value as any);
                        if (e.target.value !== "custom") {
                          setCustomStartDate("");
                          setCustomEndDate("");
                        }
                      }}
                      className="w-full px-3.5 py-2 text-sm bg-slate-900 border border-slate-750 rounded-lg text-white focus:outline-none focus:border-violet-500 transition-all cursor-pointer"
                    >
                      <option value="all">All Time</option>
                      <option value="last30">Last 30 Days</option>
                      <option value="thisMonth">This Month</option>
                      <option value="lastMonth">Last Month</option>
                      <option value="custom">Custom Range...</option>
                    </select>
                    
                    {filterDateRange === "custom" && (
                      <div className="grid grid-cols-2 gap-2 mt-1">
                        <div>
                          <span className="text-[9px] text-slate-500 block mb-1">Start Date</span>
                          <input
                            type="date"
                            value={customStartDate}
                            onChange={(e) => setCustomStartDate(e.target.value)}
                            className="w-full px-2 py-1.5 text-xs bg-slate-950 border border-slate-750 rounded text-white focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-all"
                          />
                        </div>
                        <div>
                          <span className="text-[9px] text-slate-500 block mb-1">End Date</span>
                          <input
                            type="date"
                            value={customEndDate}
                            onChange={(e) => setCustomEndDate(e.target.value)}
                            className="w-full px-2 py-1.5 text-xs bg-slate-950 border border-slate-750 rounded text-white focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-all"
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Amount Filter Column */}
                <div className="space-y-2">
                  <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Amount Range (₹)</label>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <span className="text-[9px] text-slate-500 block mb-1">Min Value</span>
                      <input
                        type="number"
                        placeholder="Min value"
                        value={minAmount}
                        onChange={(e) => setMinAmount(e.target.value)}
                        className="w-full px-3 py-2 text-xs bg-slate-900 border border-slate-750 rounded-lg text-white placeholder-slate-550 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-all"
                      />
                    </div>
                    <div>
                      <span className="text-[9px] text-slate-500 block mb-1">Max Value</span>
                      <input
                        type="number"
                        placeholder="Max value"
                        value={maxAmount}
                        onChange={(e) => setMaxAmount(e.target.value)}
                        className="w-full px-3 py-2 text-xs bg-slate-900 border border-slate-750 rounded-lg text-white placeholder-slate-550 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-all"
                      />
                    </div>
                  </div>
                </div>

                {/* Custom Toggles Column */}
                <div className="space-y-2">
                  <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Flags & Status</label>
                  <div className="flex flex-col gap-2.5 pt-1">
                    <button
                      type="button"
                      onClick={() => setShowOnlyRateLimited(!showOnlyRateLimited)}
                      className={`w-full py-2 px-3.5 text-xs border rounded-lg transition-all cursor-pointer flex items-center justify-between font-medium ${
                        showOnlyRateLimited
                          ? "bg-amber-600/15 border-amber-500/50 text-amber-300 shadow-sm"
                          : "bg-slate-900 border-slate-750 text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                        <span>AI Rate Limited Only</span>
                      </span>
                      <span className={`w-2 h-2 rounded-full ${showOnlyRateLimited ? 'bg-amber-400 animate-pulse' : 'bg-transparent'}`}></span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 text-xs font-semibold uppercase tracking-wider bg-slate-900/30">
                    <th className="px-6 py-4 w-12">
                      <input
                        type="checkbox"
                        checked={filteredTransactions.length > 0 && filteredTransactions.every(tx => selectedTxIds[tx.id])}
                        onChange={(e) => {
                          const checked = e.target.checked;
                          const newSelected = { ...selectedTxIds };
                          filteredTransactions.forEach(tx => {
                            newSelected[tx.id] = checked;
                          });
                          setSelectedTxIds(newSelected);
                        }}
                        className="rounded border-slate-750 bg-slate-900 text-violet-600 focus:ring-violet-500 focus:ring-offset-slate-900 cursor-pointer"
                      />
                    </th>
                    {renderSortHeader("Date", "date")}
                    {renderSortHeader("Account", "account_id")}
                    {renderSortHeader("Description", "description")}
                    {renderSortHeader("Category", "category")}
                    <th className="px-6 py-4">Linking</th>
                    {renderSortHeader("Amount", "amount", true)}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50 text-sm">
                  {filteredTransactions.map((tx) => (
                    <tr key={tx.id} className="hover:bg-slate-800/20 transition-colors">
                      <td className="px-6 py-4 w-12">
                        <input
                          type="checkbox"
                          checked={!!selectedTxIds[tx.id]}
                          onChange={(e) => {
                            setSelectedTxIds({
                              ...selectedTxIds,
                              [tx.id]: e.target.checked
                            });
                          }}
                          className="rounded border-slate-750 bg-slate-900 text-violet-600 focus:ring-violet-500 focus:ring-offset-slate-900 cursor-pointer"
                        />
                      </td>
                      <td className="px-6 py-4 text-slate-300 font-medium whitespace-nowrap">
                        {tx.date}
                      </td>
                      <td className="px-6 py-4 text-slate-400 font-semibold whitespace-nowrap">
                        {tx.account_id || "General"}
                      </td>
                      <td className="px-6 py-4 text-white font-medium max-w-xs truncate" title={tx.description}>
                        <div className="flex items-center gap-2">
                          <span className="truncate">{tx.description}</span>
                          {tx.ai_rate_limited && (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/25 shrink-0" title="AI categorization rate limited. Defaulted to Others.">
                              ⚠️ Rate Limited
                            </span>
                          )}
                        </div>
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
                      <td colSpan={7} className="text-center py-12 text-slate-450">
                        <div className="flex flex-col items-center justify-center space-y-3">
                          <div className="p-3 bg-slate-900/60 rounded-2xl border border-slate-800 text-slate-500">
                            <SlidersHorizontal className="h-6 w-6 animate-pulse" />
                          </div>
                          <div className="space-y-1">
                            <p className="text-sm font-semibold text-white">No transactions found</p>
                            <p className="text-xs text-slate-500 max-w-xs mx-auto">
                              No records match your active search terms or advanced filter parameters.
                            </p>
                          </div>
                          {isAnyFilterActive && (
                            <button
                              type="button"
                              onClick={handleResetFilters}
                              className="mt-2 px-3.5 py-1.5 text-xs font-semibold bg-violet-600/10 border border-violet-500/25 hover:bg-violet-600/20 text-violet-400 rounded-lg cursor-pointer transition-all"
                            >
                              Reset All Filters
                            </button>
                          )}
                        </div>
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
                  setIsMutating(true);
                  setMutationMsg("Triggering autonomous agent scan...");
                  setActiveRequests(prev => prev + 1);
                  try {
                    const res = await fetch(`${API_BASE}/agent-runs/trigger`, { method: "POST" });
                    if (res.ok) {
                      const data = await res.json();
                      alert(data.message);
                      await fetchData();
                    } else {
                      alert("Trigger failed.");
                    }
                  } catch (err) {
                    alert("Error connecting to backend trigger.");
                  } finally {
                    setTriggeringAgent(false);
                    setIsMutating(false);
                    setMutationMsg("");
                    setActiveRequests(prev => Math.max(0, prev - 1));
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
            {aiStatus.is_rate_limited && (
              <div className="p-3.5 bg-rose-500/10 border border-rose-550/20 text-rose-300 rounded-xl text-xs flex flex-col gap-1.5 leading-relaxed">
                <span className="font-semibold text-white">⚠️ AI Engine Currently Rate-Limited</span>
                <span>The Gemini API is temporarily rate-limited. AI Statement Ingestion is disabled until the block window expires (resuming in {aiStatus.seconds_remaining} seconds).</span>
              </div>
            )}
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
                disabled={aiStatus.is_rate_limited || uploading}
                className="w-full py-2.5 text-sm font-medium bg-amber-600 hover:bg-amber-500 disabled:bg-slate-800 disabled:text-slate-500 disabled:cursor-not-allowed text-white rounded-lg cursor-pointer transition-all flex items-center justify-center gap-2 shadow-lg shadow-amber-600/10"
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

      {/* Dynamic Parser Creator Modal */}
      {parserCreatorModal && (
        <div className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-xl w-full space-y-4 shadow-xl">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <SlidersHorizontal className="h-5 w-5 text-violet-500" /> Unknown Statement Format
            </h3>
            <p className="text-sm text-slate-300">
              The statement <strong className="text-violet-400">"{parserCreatorModal.filename}"</strong> has an unrecognized layout. 
              Would you like to build a custom parser using the Autonomous Parser Creator Agent?
            </p>
            <div className="space-y-1">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">Statement Text Preview (First 2000 Chars):</span>
              <pre className="font-mono text-[10px] leading-relaxed bg-slate-950 text-slate-400 p-3 rounded-lg overflow-y-auto max-h-48 border border-slate-850 whitespace-pre-wrap">
                {parserCreatorModal.textPreview || "No readable text found."}
              </pre>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              This will analyze the layout, automatically write a Python parser function, validate it in a sandbox, and dynamically register it. Future statements matching this bank format will be parsed instantly.
            </p>
            <div className="flex gap-3 pt-2">
              <button
                onClick={handleBuildParser}
                disabled={uploading}
                className="flex-1 py-2.5 text-sm font-medium bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-500 disabled:cursor-not-allowed text-white rounded-lg cursor-pointer transition-all flex items-center justify-center gap-2 shadow-lg shadow-violet-600/10"
              >
                Build Parser & Ingest
              </button>
              <button
                onClick={() => setParserCreatorModal(null)}
                className="flex-1 py-2.5 text-sm font-medium bg-slate-850 hover:bg-slate-800 text-slate-300 rounded-lg border border-slate-700 cursor-pointer transition-all"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Dashboard Update Prompt Modal */}
      {showUpdatePrompt && (
        <div className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-sm w-full space-y-4 shadow-xl text-center">
            <div className="w-12 h-12 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center mx-auto">
              <CheckCircle className="h-6 w-6" />
            </div>
            <h3 className="text-lg font-bold text-white">Statement Processed</h3>
            <p className="text-sm text-slate-300">
              The autonomous parser has completed execution and updated your financial ledger!
            </p>
            <button
              onClick={async () => {
                setShowUpdatePrompt(false);
                await fetchData();
              }}
              className="w-full py-2.5 text-sm font-medium bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg cursor-pointer transition-all shadow-lg shadow-emerald-600/10"
            >
              OK, Update Dashboard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
