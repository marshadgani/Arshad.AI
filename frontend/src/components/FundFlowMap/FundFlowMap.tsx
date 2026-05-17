import styles from './FundFlowMap.module.css';

const LEGEND = [
  { color: '#f59e0b', label: 'Income Source' },
  { color: '#fb923c', label: 'Vendor' },
  { color: '#00e5a0', label: 'Saudi Bank' },
  { color: '#e879f9', label: 'Exchange' },
  { color: '#a78bfa', label: 'NRE Account' },
  { color: '#818cf8', label: 'NRO Account' },
  { color: '#38bdf8', label: 'Savings Account' },
  { color: '#34d399', label: 'Family' },
  { color: '#f472b6', label: 'Credit Card' },
  { color: '#fbbf24', label: 'Investment' },
  { color: '#a3e635', label: 'Subscription' },
  { color: '#f97316', label: 'Expense' },
];

/* The SVG is authored in raw SVG and embedded via dangerouslySetInnerHTML.
   It uses Space Mono + Syne fonts (loaded in index.html) and hardcodes
   pixel coordinates — converting to JSX camelCase would be error-prone
   for a 200-element diagram. The content is static and fully trusted. */
const MAP_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="1820" height="1580" viewBox="0 0 1820 1580">
<defs>
  <marker id="a-vnd"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#fb923c"/></marker>
  <marker id="a-inc"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#00e5a0"/></marker>
  <marker id="a-exc"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#e879f9"/></marker>
  <marker id="a-nre"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#a78bfa"/></marker>
  <marker id="a-nro"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#818cf8"/></marker>
  <marker id="a-sav"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#38bdf8"/></marker>
  <marker id="a-fam"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#34d399"/></marker>
  <marker id="a-cc"   markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#f472b6"/></marker>
  <marker id="a-inv"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#fbbf24"/></marker>
  <marker id="a-sub"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#a3e635"/></marker>
  <marker id="a-exp"  markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#f97316"/></marker>
  <marker id="a-kaar" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#f59e0b"/></marker>
  <filter id="glow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>

<rect width="1820" height="1580" fill="#0f1117"/>

<!-- Band stripes -->
<rect x="0" y="14"   width="1820" height="116" fill="#f59e0b05"/>
<rect x="0" y="130"  width="1820" height="120" fill="#fb923c05"/>
<rect x="0" y="250"  width="1820" height="120" fill="#00e5a005"/>
<rect x="0" y="370"  width="1820" height="120" fill="#e879f905"/>
<rect x="0" y="490"  width="1820" height="120" fill="#a78bfa06"/>
<rect x="0" y="610"  width="1820" height="120" fill="#818cf806"/>
<rect x="0" y="730"  width="1820" height="140" fill="#38bdf805"/>
<rect x="0" y="870"  width="1820" height="120" fill="#34d39905"/>
<rect x="0" y="990"  width="1820" height="120" fill="#f472b605"/>
<rect x="0" y="1110" width="1820" height="140" fill="#fbbf2405"/>
<rect x="0" y="1250" width="1820" height="120" fill="#a3e63505"/>
<rect x="0" y="1370" width="1820" height="210" fill="#f9731604"/>

<!-- Band labels -->
<text x="8" y="24"   font-family="Space Mono" font-size="7" fill="#f59e0b44" letter-spacing="2">L0 · INCOME SOURCE</text>
<text x="8" y="140"  font-family="Space Mono" font-size="7" fill="#fb923c44" letter-spacing="2">L1 · VENDORS</text>
<text x="8" y="260"  font-family="Space Mono" font-size="7" fill="#00e5a044" letter-spacing="2">L2 · SAUDI BANK ACCOUNTS</text>
<text x="8" y="380"  font-family="Space Mono" font-size="7" fill="#e879f944" letter-spacing="2">L3 · EXCHANGE · ERSAL</text>
<text x="8" y="500"  font-family="Space Mono" font-size="7" fill="#a78bfa44" letter-spacing="2">L4 · NRE ACCOUNTS · INDIA</text>
<text x="8" y="620"  font-family="Space Mono" font-size="7" fill="#818cf844" letter-spacing="2">L5 · NRO ACCOUNTS · INDIA</text>
<text x="8" y="740"  font-family="Space Mono" font-size="7" fill="#38bdf844" letter-spacing="2">L6 · SAVINGS ACCOUNTS · INDIA</text>
<text x="8" y="870"  font-family="Space Mono" font-size="7" fill="#34d39944" letter-spacing="2">L7 · FAMILY EXPENSES · GPay</text>
<text x="8" y="1000" font-family="Space Mono" font-size="7" fill="#f472b644" letter-spacing="2">L8 · CREDIT CARDS</text>
<text x="8" y="1120" font-family="Space Mono" font-size="7" fill="#fbbf2444" letter-spacing="2">L9 · INVESTMENTS</text>
<text x="8" y="1260" font-family="Space Mono" font-size="7" fill="#a3e63544" letter-spacing="2">L10 · SUBSCRIPTIONS</text>
<text x="8" y="1380" font-family="Space Mono" font-size="7" fill="#f9731644" letter-spacing="2">L11 · EXPENSES</text>

<!-- BOXES -->

<!-- L0: KaarTech -->
<g filter="url(#glow)">
  <rect x="660" y="24"  width="170" height="80" rx="9" fill="#1a1208" stroke="#f59e0b" stroke-width="2"/>
  <rect x="660" y="24"  width="4"   height="80" rx="2" fill="#f59e0b"/>
  <text x="678" y="48"  font-family="Syne" font-size="13" font-weight="700" fill="#fff">KaarTech</text>
  <text x="678" y="63"  font-family="Space Mono" font-size="9" fill="#64748b">Primary Income Source</text>
  <text x="678" y="76"  font-family="Space Mono" font-size="9" fill="#64748b">Saudi Arabia</text>
  <rect x="678" y="84"  width="68" height="8" rx="3" fill="#f59e0b22"/>
  <text x="712" y="91"  font-family="Space Mono" font-size="7" fill="#f59e0b" text-anchor="middle">INCOME SOURCE</text>
</g>

<!-- L1: JawaHR -->
<rect x="230" y="140" width="165" height="80" rx="9" fill="#12151c" stroke="#fb923c" stroke-width="1.5"/>
<rect x="230" y="140" width="4"   height="80" rx="2" fill="#fb923c"/>
<text x="248" y="163" font-family="Syne" font-size="12" font-weight="700" fill="#fff">JawaHR</text>
<text x="248" y="178" font-family="Space Mono" font-size="9" fill="#64748b">Vendor · Al Rajhi</text>
<text x="248" y="191" font-family="Space Mono" font-size="9" fill="#64748b">Saudi Arabia</text>
<rect x="248" y="201" width="44" height="8" rx="3" fill="#fb923c22"/>
<text x="270" y="208" font-family="Space Mono" font-size="7" fill="#fb923c" text-anchor="middle">VENDOR</text>

<!-- L1: Luminous Rose -->
<rect x="630" y="140" width="165" height="80" rx="9" fill="#12151c" stroke="#fb923c" stroke-width="1.5"/>
<rect x="630" y="140" width="4"   height="80" rx="2" fill="#fb923c"/>
<text x="648" y="163" font-family="Syne" font-size="12" font-weight="700" fill="#fff">Luminous Rose</text>
<text x="648" y="178" font-family="Space Mono" font-size="9" fill="#64748b">Vendor · Al Rajhi</text>
<text x="648" y="191" font-family="Space Mono" font-size="9" fill="#64748b">Saudi Arabia</text>
<rect x="648" y="201" width="44" height="8" rx="3" fill="#fb923c22"/>
<text x="670" y="208" font-family="Space Mono" font-size="7" fill="#fb923c" text-anchor="middle">VENDOR</text>

<!-- L2: Al Rajhi -->
<rect x="30"  y="260" width="165" height="80" rx="9" fill="#12151c" stroke="#00e5a0" stroke-width="1.5"/>
<rect x="30"  y="260" width="4"   height="80" rx="2" fill="#00e5a0"/>
<text x="48"  y="283" font-family="Syne" font-size="12" font-weight="700" fill="#fff">Al Rajhi Bank</text>
<text x="48"  y="298" font-family="Space Mono" font-size="9" fill="#64748b">Saudi Arabia</text>
<text x="48"  y="311" font-family="Space Mono" font-size="9" fill="#64748b">via Vendors</text>
<rect x="48"  y="321" width="52" height="8" rx="3" fill="#00e5a022"/>
<text x="74"  y="328" font-family="Space Mono" font-size="7" fill="#00e5a0" text-anchor="middle">MONTHLY</text>

<!-- L2: STC Dormant -->
<rect x="830" y="260" width="165" height="80" rx="9" fill="#12151c" stroke="#2d3748" stroke-width="1.5"/>
<rect x="830" y="260" width="4"   height="80" rx="2" fill="#2d3748"/>
<text x="848" y="283" font-family="Syne" font-size="12" font-weight="700" fill="#374151">STC Bank</text>
<text x="848" y="298" font-family="Space Mono" font-size="9" fill="#2d3748">Saudi Arabia</text>
<text x="848" y="311" font-family="Space Mono" font-size="9" fill="#2d3748">No active income</text>
<rect x="848" y="321" width="80" height="8" rx="3" fill="#2d374822"/>
<text x="888" y="328" font-family="Space Mono" font-size="7" fill="#374151" text-anchor="middle">DORMANT · NO INFLOW</text>

<!-- L2: Amex -->
<rect x="1630" y="260" width="165" height="80" rx="9" fill="#12151c" stroke="#00e5a0" stroke-width="1.5"/>
<rect x="1630" y="260" width="4"   height="80" rx="2" fill="#00e5a0"/>
<text x="1648" y="283" font-family="Syne" font-size="12" font-weight="700" fill="#fff">Amex Bank</text>
<text x="1648" y="298" font-family="Space Mono" font-size="9" fill="#64748b">Saudi Arabia</text>
<text x="1648" y="311" font-family="Space Mono" font-size="9" fill="#64748b">Direct · KaarTech</text>
<rect x="1648" y="321" width="52" height="8" rx="3" fill="#00e5a022"/>
<text x="1674" y="328" font-family="Space Mono" font-size="7" fill="#00e5a0" text-anchor="middle">MONTHLY</text>

<!-- L3: Ersal -->
<rect x="1630" y="380" width="165" height="80" rx="9" fill="#12151c" stroke="#e879f9" stroke-width="1.5"/>
<rect x="1630" y="380" width="4"   height="80" rx="2" fill="#e879f9"/>
<text x="1648" y="403" font-family="Syne" font-size="12" font-weight="700" fill="#fff">Ersal Exchange</text>
<text x="1648" y="418" font-family="Space Mono" font-size="9" fill="#64748b">Amex only · SAR→INR</text>
<text x="1648" y="431" font-family="Space Mono" font-size="9" fill="#64748b">Saudi Arabia</text>
<rect x="1648" y="441" width="78" height="8" rx="3" fill="#e879f922"/>
<text x="1687" y="448" font-family="Space Mono" font-size="7" fill="#e879f9" text-anchor="middle">EXCHANGE · MANUAL</text>

<!-- L4: ICICI NRE -->
<g filter="url(#glow)">
  <rect x="230" y="500" width="175" height="90" rx="9" fill="#140f1f" stroke="#a78bfa" stroke-width="2"/>
  <rect x="230" y="500" width="4"   height="90" rx="2" fill="#a78bfa"/>
  <text x="248" y="524" font-family="Syne" font-size="12" font-weight="700" fill="#fff">ICICI NRE Account</text>
  <text x="248" y="539" font-family="Space Mono" font-size="9" fill="#64748b">Non-Resident External</text>
  <text x="248" y="552" font-family="Space Mono" font-size="9" fill="#64748b">India · Central Hub</text>
  <rect x="248" y="562" width="42" height="8" rx="3" fill="#a78bfa22"/>
  <text x="269" y="569" font-family="Space Mono" font-size="7" fill="#a78bfa" text-anchor="middle">NRE HUB</text>
  <rect x="296" y="562" width="62" height="8" rx="3" fill="#a78bfa22"/>
  <text x="327" y="569" font-family="Space Mono" font-size="7" fill="#a78bfa" text-anchor="middle">TAX-FREE · IND</text>
</g>

<!-- L4: IOB NRE -->
<g filter="url(#glow)">
  <rect x="1430" y="500" width="175" height="90" rx="9" fill="#140f1f" stroke="#a78bfa" stroke-width="2"/>
  <rect x="1430" y="500" width="4"   height="90" rx="2" fill="#a78bfa"/>
  <text x="1448" y="524" font-family="Syne" font-size="12" font-weight="700" fill="#fff">IOB NRE Account</text>
  <text x="1448" y="539" font-family="Space Mono" font-size="9" fill="#64748b">Indian Overseas Bank</text>
  <text x="1448" y="552" font-family="Space Mono" font-size="9" fill="#64748b">India · NRE</text>
  <rect x="1448" y="562" width="38" height="8" rx="3" fill="#a78bfa22"/>
  <text x="1467" y="569" font-family="Space Mono" font-size="7" fill="#a78bfa" text-anchor="middle">NRE</text>
  <rect x="1492" y="562" width="62" height="8" rx="3" fill="#a78bfa22"/>
  <text x="1523" y="569" font-family="Space Mono" font-size="7" fill="#a78bfa" text-anchor="middle">TAX-FREE · IND</text>
</g>

<!-- L5: ICICI NRO -->
<rect x="230" y="620" width="165" height="80" rx="9" fill="#12151c" stroke="#818cf8" stroke-width="1.5"/>
<rect x="230" y="620" width="4"   height="80" rx="2" fill="#818cf8"/>
<text x="248" y="643" font-family="Syne" font-size="11" font-weight="700" fill="#fff">ICICI NRO</text>
<text x="248" y="658" font-family="Space Mono" font-size="9" fill="#64748b">Non-Resident Ordinary</text>
<text x="248" y="671" font-family="Space Mono" font-size="9" fill="#64748b">India</text>
<rect x="248" y="681" width="36" height="8" rx="3" fill="#818cf822"/>
<text x="266" y="688" font-family="Space Mono" font-size="7" fill="#818cf8" text-anchor="middle">NRO</text>

<!-- L5: IOB NRO -->
<rect x="1430" y="620" width="165" height="80" rx="9" fill="#12151c" stroke="#818cf8" stroke-width="1.5"/>
<rect x="1430" y="620" width="4"   height="80" rx="2" fill="#818cf8"/>
<text x="1448" y="643" font-family="Syne" font-size="11" font-weight="700" fill="#fff">IOB NRO</text>
<text x="1448" y="658" font-family="Space Mono" font-size="9" fill="#64748b">Indian Overseas Bank</text>
<text x="1448" y="671" font-family="Space Mono" font-size="9" fill="#64748b">India · NRO</text>
<rect x="1448" y="681" width="36" height="8" rx="3" fill="#818cf822"/>
<text x="1466" y="688" font-family="Space Mono" font-size="7" fill="#818cf8" text-anchor="middle">NRO</text>

<!-- L6: SBI -->
<rect x="30"  y="750" width="165" height="80" rx="9" fill="#12151c" stroke="#38bdf8" stroke-width="1.5"/>
<rect x="30"  y="750" width="4"   height="80" rx="2" fill="#38bdf8"/>
<text x="48"  y="773" font-family="Syne" font-size="11" font-weight="700" fill="#fff">SBI Savings</text>
<text x="48"  y="788" font-family="Space Mono" font-size="9" fill="#64748b">State Bank of India</text>
<text x="48"  y="801" font-family="Space Mono" font-size="9" fill="#64748b">Funded by IDBI</text>
<rect x="48"  y="811" width="50" height="8" rx="3" fill="#38bdf822"/>
<text x="73"  y="818" font-family="Space Mono" font-size="7" fill="#38bdf8" text-anchor="middle">SAVINGS</text>

<!-- L6: IDBI -->
<rect x="630" y="750" width="165" height="80" rx="9" fill="#12151c" stroke="#38bdf8" stroke-width="2"/>
<rect x="630" y="750" width="4"   height="80" rx="2" fill="#38bdf8"/>
<text x="648" y="773" font-family="Syne" font-size="11" font-weight="700" fill="#fff">IDBI Savings</text>
<text x="648" y="788" font-family="Space Mono" font-size="9" fill="#64748b">IDBI Bank · India</text>
<text x="648" y="801" font-family="Space Mono" font-size="9" fill="#64748b">KaarTech Direct</text>
<rect x="648" y="811" width="50" height="8" rx="3" fill="#38bdf822"/>
<text x="673" y="818" font-family="Space Mono" font-size="7" fill="#38bdf8" text-anchor="middle">SAVINGS · HUB</text>

<!-- L6: BOB -->
<rect x="1030" y="750" width="165" height="80" rx="9" fill="#12151c" stroke="#38bdf8" stroke-width="1.5"/>
<rect x="1030" y="750" width="4"   height="80" rx="2" fill="#38bdf8"/>
<text x="1048" y="773" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Bank of Baroda</text>
<text x="1048" y="788" font-family="Space Mono" font-size="9" fill="#64748b">BOB Savings · India</text>
<text x="1048" y="801" font-family="Space Mono" font-size="9" fill="#64748b">Funded by IDBI</text>
<rect x="1048" y="811" width="50" height="8" rx="3" fill="#38bdf822"/>
<text x="1073" y="818" font-family="Space Mono" font-size="7" fill="#38bdf8" text-anchor="middle">SAVINGS</text>

<!-- L7: Mahalakshmi -->
<rect x="430" y="880" width="165" height="80" rx="9" fill="#12151c" stroke="#34d399" stroke-width="1.5"/>
<rect x="430" y="880" width="4"   height="80" rx="2" fill="#34d399"/>
<text x="448" y="900" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Mahalakshmi</text>
<text x="448" y="915" font-family="Space Mono" font-size="9" fill="#64748b">Spouse · ICICI Savings</text>
<text x="448" y="928" font-family="Space Mono" font-size="9" fill="#64748b">GPay · India</text>
<rect x="448" y="938" width="40" height="8" rx="3" fill="#34d39922"/>
<text x="468" y="945" font-family="Space Mono" font-size="7" fill="#34d399" text-anchor="middle">GPAY</text>
<rect x="494" y="938" width="44" height="8" rx="3" fill="#34d39922"/>
<text x="516" y="945" font-family="Space Mono" font-size="7" fill="#34d399" text-anchor="middle">MONTHLY</text>

<!-- L7: Arhan -->
<rect x="830" y="880" width="165" height="80" rx="9" fill="#12151c" stroke="#34d399" stroke-width="1.5"/>
<rect x="830" y="880" width="4"   height="80" rx="2" fill="#34d399"/>
<text x="848" y="900" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Arhan</text>
<text x="848" y="915" font-family="Space Mono" font-size="9" fill="#64748b">Son · ICICI Savings</text>
<text x="848" y="928" font-family="Space Mono" font-size="9" fill="#64748b">GPay · India</text>
<rect x="848" y="938" width="40" height="8" rx="3" fill="#34d39922"/>
<text x="868" y="945" font-family="Space Mono" font-size="7" fill="#34d399" text-anchor="middle">GPAY</text>
<rect x="894" y="938" width="44" height="8" rx="3" fill="#34d39922"/>
<text x="916" y="945" font-family="Space Mono" font-size="7" fill="#34d399" text-anchor="middle">MONTHLY</text>

<!-- L7: Jerina -->
<rect x="1230" y="880" width="165" height="80" rx="9" fill="#12151c" stroke="#34d399" stroke-width="1.5"/>
<rect x="1230" y="880" width="4"   height="80" rx="2" fill="#34d399"/>
<text x="1248" y="900" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Jerina · Mother</text>
<text x="1248" y="915" font-family="Space Mono" font-size="9" fill="#64748b">ICICI Savings · India</text>
<text x="1248" y="928" font-family="Space Mono" font-size="9" fill="#64748b">GPay</text>
<rect x="1248" y="938" width="40" height="8" rx="3" fill="#34d39922"/>
<text x="1268" y="945" font-family="Space Mono" font-size="7" fill="#34d399" text-anchor="middle">GPAY</text>
<rect x="1294" y="938" width="44" height="8" rx="3" fill="#34d39922"/>
<text x="1316" y="945" font-family="Space Mono" font-size="7" fill="#34d399" text-anchor="middle">MONTHLY</text>

<!-- L8: ICICI Coral CC -->
<rect x="230" y="1000" width="165" height="80" rx="9" fill="#12151c" stroke="#f472b6" stroke-width="1.5"/>
<rect x="230" y="1000" width="4"   height="80" rx="2" fill="#f472b6"/>
<text x="248" y="1020" font-family="Syne" font-size="11" font-weight="700" fill="#fff">ICICI Coral CC</text>
<text x="248" y="1035" font-family="Space Mono" font-size="9" fill="#64748b">Subscriptions</text>
<text x="248" y="1048" font-family="Space Mono" font-size="9" fill="#64748b">Both NRE Accounts</text>
<rect x="248" y="1058" width="68" height="8" rx="3" fill="#f472b622"/>
<text x="282" y="1065" font-family="Space Mono" font-size="7" fill="#f472b6" text-anchor="middle">CREDIT · MONTHLY</text>

<!-- L8: ICICI Rubyx CC -->
<rect x="830" y="1000" width="165" height="80" rx="9" fill="#12151c" stroke="#f472b6" stroke-width="1.5"/>
<rect x="830" y="1000" width="4"   height="80" rx="2" fill="#f472b6"/>
<text x="848" y="1020" font-family="Syne" font-size="11" font-weight="700" fill="#fff">ICICI Rubyx CC</text>
<text x="848" y="1035" font-family="Space Mono" font-size="9" fill="#64748b">Shopping</text>
<text x="848" y="1048" font-family="Space Mono" font-size="9" fill="#64748b">Both NRE Accounts</text>
<rect x="848" y="1058" width="68" height="8" rx="3" fill="#f472b622"/>
<text x="882" y="1065" font-family="Space Mono" font-size="7" fill="#f472b6" text-anchor="middle">CREDIT · SHOPPING</text>

<!-- L8: SBI Lifestyle CC -->
<rect x="1430" y="1000" width="165" height="80" rx="9" fill="#12151c" stroke="#f472b6" stroke-width="1.5"/>
<rect x="1430" y="1000" width="4"   height="80" rx="2" fill="#f472b6"/>
<text x="1448" y="1020" font-family="Syne" font-size="11" font-weight="700" fill="#fff">SBI Lifestyle CC</text>
<text x="1448" y="1035" font-family="Space Mono" font-size="9" fill="#64748b">Shopping</text>
<text x="1448" y="1048" font-family="Space Mono" font-size="9" fill="#64748b">Both NRE Accounts</text>
<rect x="1448" y="1058" width="68" height="8" rx="3" fill="#f472b622"/>
<text x="1482" y="1065" font-family="Space Mono" font-size="7" fill="#f472b6" text-anchor="middle">CREDIT · SHOPPING</text>

<!-- L9: Gold ETF -->
<rect x="30"  y="1130" width="165" height="80" rx="9" fill="#121509" stroke="#fbbf24" stroke-width="1.5"/>
<rect x="30"  y="1130" width="4"   height="80" rx="2" fill="#fbbf24"/>
<text x="48"  y="1151" font-family="Syne" font-size="11" font-weight="700" fill="#fff">ICICI Gold ETF</text>
<text x="48"  y="1166" font-family="Space Mono" font-size="9" fill="#64748b">Upstox SIP · GPay</text>
<text x="48"  y="1179" font-family="Space Mono" font-size="9" fill="#64748b">SBI Savings · India</text>
<rect x="48"  y="1189" width="34" height="8" rx="3" fill="#fbbf2422"/>
<text x="65"  y="1196" font-family="Space Mono" font-size="7" fill="#fbbf24" text-anchor="middle">SIP</text>
<rect x="88"  y="1189" width="38" height="8" rx="3" fill="#c084fc22"/>
<text x="107" y="1196" font-family="Space Mono" font-size="7" fill="#c084fc" text-anchor="middle">GPAY</text>

<!-- L9: HDFC Home Loan -->
<rect x="430" y="1130" width="165" height="80" rx="9" fill="#121509" stroke="#fbbf24" stroke-width="1.5"/>
<rect x="430" y="1130" width="4"   height="80" rx="2" fill="#fbbf24"/>
<text x="448" y="1151" font-family="Syne" font-size="11" font-weight="700" fill="#fff">HDFC Home Loan</text>
<text x="448" y="1166" font-family="Space Mono" font-size="9" fill="#64748b">EMI · IDBI Savings</text>
<text x="448" y="1179" font-family="Space Mono" font-size="9" fill="#64748b">India</text>
<rect x="448" y="1189" width="34" height="8" rx="3" fill="#fbbf2422"/>
<text x="465" y="1196" font-family="Space Mono" font-size="7" fill="#fbbf24" text-anchor="middle">AUTO</text>
<rect x="488" y="1189" width="50" height="8" rx="3" fill="#fbbf2422"/>
<text x="513" y="1196" font-family="Space Mono" font-size="7" fill="#fbbf24" text-anchor="middle">MONTHLY</text>

<!-- L9: ICICI Term Life -->
<rect x="830" y="1130" width="165" height="80" rx="9" fill="#121509" stroke="#fbbf24" stroke-width="1.5"/>
<rect x="830" y="1130" width="4"   height="80" rx="2" fill="#fbbf24"/>
<text x="848" y="1151" font-family="Syne" font-size="11" font-weight="700" fill="#fff">ICICI Term Life</text>
<text x="848" y="1166" font-family="Space Mono" font-size="9" fill="#64748b">Prudential Insurance</text>
<text x="848" y="1179" font-family="Space Mono" font-size="9" fill="#64748b">ICICI NRE · India</text>
<rect x="848" y="1189" width="34" height="8" rx="3" fill="#fbbf2422"/>
<text x="865" y="1196" font-family="Space Mono" font-size="7" fill="#fbbf24" text-anchor="middle">AUTO</text>
<rect x="888" y="1189" width="50" height="8" rx="3" fill="#fbbf2422"/>
<text x="913" y="1196" font-family="Space Mono" font-size="7" fill="#fbbf24" text-anchor="middle">MONTHLY</text>

<!-- L9: Bajaj Alliance -->
<rect x="1230" y="1130" width="165" height="80" rx="9" fill="#121509" stroke="#fbbf24" stroke-width="1.5"/>
<rect x="1230" y="1130" width="4"   height="80" rx="2" fill="#fbbf24"/>
<text x="1248" y="1151" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Bajaj Alliance</text>
<text x="1248" y="1166" font-family="Space Mono" font-size="9" fill="#64748b">Goal Suraksha POS</text>
<text x="1248" y="1179" font-family="Space Mono" font-size="9" fill="#64748b">IDBI Savings · India</text>
<rect x="1248" y="1189" width="34" height="8" rx="3" fill="#fbbf2422"/>
<text x="1265" y="1196" font-family="Space Mono" font-size="7" fill="#fbbf24" text-anchor="middle">AUTO</text>
<rect x="1288" y="1189" width="50" height="8" rx="3" fill="#fbbf2422"/>
<text x="1313" y="1196" font-family="Space Mono" font-size="7" fill="#fbbf24" text-anchor="middle">MONTHLY</text>

<!-- L10: iCloud -->
<rect x="230" y="1270" width="155" height="80" rx="9" fill="#0f1512" stroke="#a3e635" stroke-width="1.5"/>
<rect x="230" y="1270" width="4"   height="80" rx="2" fill="#a3e635"/>
<text x="248" y="1291" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Apple iCloud</text>
<text x="248" y="1306" font-family="Space Mono" font-size="9" fill="#64748b">ICICI Coral CC</text>
<text x="248" y="1319" font-family="Space Mono" font-size="9" fill="#64748b">India</text>
<rect x="248" y="1329" width="34" height="8" rx="3" fill="#a3e63522"/>
<text x="265" y="1336" font-family="Space Mono" font-size="7" fill="#a3e635" text-anchor="middle">AUTO</text>

<!-- L10: Airtel -->
<rect x="430" y="1270" width="155" height="80" rx="9" fill="#0f1512" stroke="#a3e635" stroke-width="1.5"/>
<rect x="430" y="1270" width="4"   height="80" rx="2" fill="#a3e635"/>
<text x="448" y="1291" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Airtel Postpaid</text>
<text x="448" y="1306" font-family="Space Mono" font-size="9" fill="#64748b">ICICI Coral CC</text>
<text x="448" y="1319" font-family="Space Mono" font-size="9" fill="#64748b">India</text>
<rect x="448" y="1329" width="34" height="8" rx="3" fill="#a3e63522"/>
<text x="465" y="1336" font-family="Space Mono" font-size="7" fill="#a3e635" text-anchor="middle">AUTO</text>

<!-- L10: Netflix -->
<rect x="630" y="1270" width="155" height="80" rx="9" fill="#0f1512" stroke="#a3e635" stroke-width="1.5"/>
<rect x="630" y="1270" width="4"   height="80" rx="2" fill="#a3e635"/>
<text x="648" y="1291" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Netflix</text>
<text x="648" y="1306" font-family="Space Mono" font-size="9" fill="#64748b">ICICI Coral CC</text>
<text x="648" y="1319" font-family="Space Mono" font-size="9" fill="#64748b">India</text>
<rect x="648" y="1329" width="34" height="8" rx="3" fill="#a3e63522"/>
<text x="665" y="1336" font-family="Space Mono" font-size="7" fill="#a3e635" text-anchor="middle">AUTO</text>

<!-- L10: Claude -->
<rect x="830" y="1270" width="155" height="80" rx="9" fill="#0f1512" stroke="#a3e635" stroke-width="1.5"/>
<rect x="830" y="1270" width="4"   height="80" rx="2" fill="#a3e635"/>
<text x="848" y="1291" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Claude</text>
<text x="848" y="1306" font-family="Space Mono" font-size="9" fill="#64748b">ICICI Coral CC</text>
<text x="848" y="1319" font-family="Space Mono" font-size="9" fill="#64748b">India</text>
<rect x="848" y="1329" width="34" height="8" rx="3" fill="#a3e63522"/>
<text x="865" y="1336" font-family="Space Mono" font-size="7" fill="#a3e635" text-anchor="middle">AUTO</text>

<!-- L11: Shopping Rubyx -->
<rect x="830" y="1400" width="165" height="80" rx="9" fill="#12100c" stroke="#f97316" stroke-width="1.5"/>
<rect x="830" y="1400" width="4"   height="80" rx="2" fill="#f97316"/>
<text x="848" y="1421" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Shopping</text>
<text x="848" y="1436" font-family="Space Mono" font-size="9" fill="#64748b">ICICI Rubyx CC</text>
<text x="848" y="1449" font-family="Space Mono" font-size="9" fill="#64748b">India</text>
<rect x="848" y="1459" width="50" height="8" rx="3" fill="#f9731622"/>
<text x="873" y="1466" font-family="Space Mono" font-size="7" fill="#f97316" text-anchor="middle">MANUAL</text>

<!-- L11: Shopping SBI Lifestyle -->
<rect x="1230" y="1400" width="165" height="80" rx="9" fill="#12100c" stroke="#f97316" stroke-width="1.5"/>
<rect x="1230" y="1400" width="4"   height="80" rx="2" fill="#f97316"/>
<text x="1248" y="1421" font-family="Syne" font-size="11" font-weight="700" fill="#fff">Shopping</text>
<text x="1248" y="1436" font-family="Space Mono" font-size="9" fill="#64748b">SBI Lifestyle CC</text>
<text x="1248" y="1449" font-family="Space Mono" font-size="9" fill="#64748b">India</text>
<rect x="1248" y="1459" width="50" height="8" rx="3" fill="#f9731622"/>
<text x="1273" y="1466" font-family="Space Mono" font-size="7" fill="#f97316" text-anchor="middle">MANUAL</text>

<!-- ARROWS -->

<!-- KaarTech → JawaHR -->
<line x1="712" y1="104" x2="712" y2="118" stroke="#fb923c" stroke-width="1.5"/>
<line x1="712" y1="118" x2="312" y2="118" stroke="#fb923c" stroke-width="1.5"/>
<line x1="312" y1="118" x2="312" y2="140" stroke="#fb923c" stroke-width="1.5" marker-end="url(#a-vnd)"/>

<!-- KaarTech → Luminous Rose -->
<line x1="722" y1="104" x2="722" y2="128" stroke="#fb923c" stroke-width="1.5"/>
<line x1="722" y1="128" x2="712" y2="128" stroke="#fb923c" stroke-width="1.5"/>
<line x1="712" y1="128" x2="712" y2="140" stroke="#fb923c" stroke-width="1.5" marker-end="url(#a-vnd)"/>

<!-- KaarTech → Amex -->
<line x1="830" y1="64"  x2="1712" y2="64"  stroke="#00e5a0" stroke-width="1.5"/>
<line x1="1712" y1="64"  x2="1712" y2="260" stroke="#00e5a0" stroke-width="1.5" marker-end="url(#a-inc)"/>

<!-- KaarTech → IDBI Direct -->
<line x1="662" y1="104" x2="662" y2="742" stroke="#f59e0b" stroke-width="1.5"/>
<line x1="662" y1="742" x2="712" y2="742" stroke="#f59e0b" stroke-width="1.5"/>
<line x1="712" y1="742" x2="712" y2="750" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#a-kaar)"/>
<rect x="622" y="390" width="54" height="14" rx="3" fill="#1a1208" opacity="0.9"/>
<text x="649" y="400" font-family="Space Mono" font-size="8" fill="#f59e0b" text-anchor="middle">Direct</text>

<!-- JawaHR → Al Rajhi -->
<line x1="312" y1="220" x2="312" y2="248" stroke="#00e5a0" stroke-width="1.5"/>
<line x1="312" y1="248" x2="112" y2="248" stroke="#00e5a0" stroke-width="1.5"/>
<line x1="112" y1="248" x2="112" y2="260" stroke="#00e5a0" stroke-width="1.5" marker-end="url(#a-inc)"/>

<!-- Luminous Rose → Al Rajhi -->
<line x1="712" y1="220" x2="712" y2="244" stroke="#00e5a0" stroke-width="1.5"/>
<line x1="712" y1="244" x2="122" y2="244" stroke="#00e5a0" stroke-width="1.5"/>
<line x1="122" y1="244" x2="122" y2="260" stroke="#00e5a0" stroke-width="1.5" marker-end="url(#a-inc)"/>

<!-- Amex → Ersal -->
<line x1="1712" y1="340" x2="1712" y2="380" stroke="#e879f9" stroke-width="1.5" marker-end="url(#a-exc)"/>

<!-- Al Rajhi → ICICI NRE -->
<line x1="112" y1="340" x2="112" y2="488" stroke="#a78bfa" stroke-width="1.5"/>
<line x1="112" y1="488" x2="317" y2="488" stroke="#a78bfa" stroke-width="1.5"/>
<line x1="317" y1="488" x2="317" y2="500" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#a-nre)"/>

<!-- Al Rajhi → IOB NRE -->
<line x1="122" y1="340" x2="122" y2="478" stroke="#a78bfa" stroke-width="1.5"/>
<line x1="122" y1="478" x2="1517" y2="478" stroke="#a78bfa" stroke-width="1.5"/>
<line x1="1517" y1="478" x2="1517" y2="500" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#a-nre)"/>

<!-- Ersal → ICICI NRE -->
<line x1="1692" y1="460" x2="1692" y2="494" stroke="#a78bfa" stroke-width="1.5"/>
<line x1="1692" y1="494" x2="327" y2="494" stroke="#a78bfa" stroke-width="1.5"/>
<line x1="327" y1="494" x2="327" y2="500" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#a-nre)"/>

<!-- Ersal → IOB NRE -->
<line x1="1712" y1="460" x2="1712" y2="490" stroke="#a78bfa" stroke-width="1.5"/>
<line x1="1712" y1="490" x2="1527" y2="490" stroke="#a78bfa" stroke-width="1.5"/>
<line x1="1527" y1="490" x2="1527" y2="500" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#a-nre)"/>

<!-- ICICI NRE → ICICI NRO -->
<line x1="317" y1="590" x2="317" y2="620" stroke="#818cf8" stroke-width="1.5" marker-end="url(#a-nro)"/>

<!-- IOB NRE → IOB NRO -->
<line x1="1517" y1="590" x2="1517" y2="620" stroke="#818cf8" stroke-width="1.5" marker-end="url(#a-nro)"/>

<!-- IDBI → SBI -->
<line x1="630" y1="790" x2="608" y2="790" stroke="#38bdf8" stroke-width="1.5"/>
<line x1="608" y1="790" x2="608" y2="808" stroke="#38bdf8" stroke-width="1.5"/>
<line x1="608" y1="808" x2="195" y2="808" stroke="#38bdf8" stroke-width="1.5"/>
<line x1="195" y1="808" x2="195" y2="790" stroke="#38bdf8" stroke-width="1.5" marker-end="url(#a-sav)"/>

<!-- IDBI → BOB -->
<line x1="795" y1="790" x2="820" y2="790" stroke="#38bdf8" stroke-width="1.5"/>
<line x1="820" y1="790" x2="820" y2="812" stroke="#38bdf8" stroke-width="1.5"/>
<line x1="820" y1="812" x2="1030" y2="812" stroke="#38bdf8" stroke-width="1.5"/>
<line x1="1030" y1="812" x2="1030" y2="790" stroke="#38bdf8" stroke-width="1.5" marker-end="url(#a-sav)"/>

<!-- NRE → Family -->
<line x1="337" y1="590" x2="337" y2="868" stroke="#34d399" stroke-width="1.5"/>
<line x1="337" y1="868" x2="512" y2="868" stroke="#34d399" stroke-width="1.5"/>
<line x1="512" y1="868" x2="512" y2="880" stroke="#34d399" stroke-width="1.5" marker-end="url(#a-fam)"/>
<line x1="347" y1="590" x2="347" y2="864" stroke="#34d399" stroke-width="1.5"/>
<line x1="347" y1="864" x2="912" y2="864" stroke="#34d399" stroke-width="1.5"/>
<line x1="912" y1="864" x2="912" y2="880" stroke="#34d399" stroke-width="1.5" marker-end="url(#a-fam)"/>
<line x1="357" y1="590" x2="357" y2="860" stroke="#34d399" stroke-width="1.5"/>
<line x1="357" y1="860" x2="1312" y2="860" stroke="#34d399" stroke-width="1.5"/>
<line x1="1312" y1="860" x2="1312" y2="880" stroke="#34d399" stroke-width="1.5" marker-end="url(#a-fam)"/>
<line x1="1497" y1="590" x2="1497" y2="856" stroke="#34d399" stroke-width="1.5"/>
<line x1="1497" y1="856" x2="522" y2="856" stroke="#34d399" stroke-width="1.5"/>
<line x1="522" y1="856" x2="522" y2="880" stroke="#34d399" stroke-width="1.5" marker-end="url(#a-fam)"/>
<line x1="1507" y1="590" x2="1507" y2="852" stroke="#34d399" stroke-width="1.5"/>
<line x1="1507" y1="852" x2="922" y2="852" stroke="#34d399" stroke-width="1.5"/>
<line x1="922" y1="852" x2="922" y2="880" stroke="#34d399" stroke-width="1.5" marker-end="url(#a-fam)"/>
<line x1="1517" y1="590" x2="1517" y2="848" stroke="#34d399" stroke-width="1.5"/>
<line x1="1517" y1="848" x2="1322" y2="848" stroke="#34d399" stroke-width="1.5"/>
<line x1="1322" y1="848" x2="1322" y2="880" stroke="#34d399" stroke-width="1.5" marker-end="url(#a-fam)"/>

<!-- NRE → Credit Cards -->
<line x1="307" y1="590" x2="307" y2="1000" stroke="#f472b6" stroke-width="1.5" marker-end="url(#a-cc)"/>
<line x1="367" y1="590" x2="367" y2="984" stroke="#f472b6" stroke-width="1.5"/>
<line x1="367" y1="984" x2="912" y2="984" stroke="#f472b6" stroke-width="1.5"/>
<line x1="912" y1="984" x2="912" y2="1000" stroke="#f472b6" stroke-width="1.5" marker-end="url(#a-cc)"/>
<line x1="377" y1="590" x2="377" y2="980" stroke="#f472b6" stroke-width="1.5"/>
<line x1="377" y1="980" x2="1512" y2="980" stroke="#f472b6" stroke-width="1.5"/>
<line x1="1512" y1="980" x2="1512" y2="1000" stroke="#f472b6" stroke-width="1.5" marker-end="url(#a-cc)"/>
<line x1="1467" y1="590" x2="1467" y2="992" stroke="#f472b6" stroke-width="1.5"/>
<line x1="1467" y1="992" x2="297" y2="992" stroke="#f472b6" stroke-width="1.5"/>
<line x1="297" y1="992" x2="297" y2="1000" stroke="#f472b6" stroke-width="1.5" marker-end="url(#a-cc)"/>
<line x1="1477" y1="590" x2="1477" y2="988" stroke="#f472b6" stroke-width="1.5"/>
<line x1="1477" y1="988" x2="902" y2="988" stroke="#f472b6" stroke-width="1.5"/>
<line x1="902" y1="988" x2="902" y2="1000" stroke="#f472b6" stroke-width="1.5" marker-end="url(#a-cc)"/>
<line x1="1517" y1="590" x2="1517" y2="1000" stroke="#f472b6" stroke-width="1.5" marker-end="url(#a-cc)"/>

<!-- SBI → Gold ETF -->
<line x1="112" y1="830" x2="112" y2="1130" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#a-inv)"/>

<!-- IDBI → HDFC Home Loan -->
<line x1="692" y1="830" x2="692" y2="1108" stroke="#fbbf24" stroke-width="1.5"/>
<line x1="692" y1="1108" x2="512" y2="1108" stroke="#fbbf24" stroke-width="1.5"/>
<line x1="512" y1="1108" x2="512" y2="1130" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#a-inv)"/>

<!-- ICICI NRE → ICICI Term Life -->
<line x1="387" y1="590" x2="387" y2="1104" stroke="#fbbf24" stroke-width="1.5"/>
<line x1="387" y1="1104" x2="912" y2="1104" stroke="#fbbf24" stroke-width="1.5"/>
<line x1="912" y1="1104" x2="912" y2="1130" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#a-inv)"/>

<!-- IDBI → Bajaj Alliance -->
<line x1="702" y1="830" x2="702" y2="1112" stroke="#fbbf24" stroke-width="1.5"/>
<line x1="702" y1="1112" x2="1312" y2="1112" stroke="#fbbf24" stroke-width="1.5"/>
<line x1="1312" y1="1112" x2="1312" y2="1130" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#a-inv)"/>

<!-- Coral → Subscriptions -->
<line x1="287" y1="1080" x2="287" y2="1248" stroke="#a3e635" stroke-width="1.5"/>
<line x1="287" y1="1248" x2="312" y2="1248" stroke="#a3e635" stroke-width="1.5"/>
<line x1="312" y1="1248" x2="312" y2="1270" stroke="#a3e635" stroke-width="1.5" marker-end="url(#a-sub)"/>
<line x1="302" y1="1080" x2="302" y2="1244" stroke="#a3e635" stroke-width="1.5"/>
<line x1="302" y1="1244" x2="512" y2="1244" stroke="#a3e635" stroke-width="1.5"/>
<line x1="512" y1="1244" x2="512" y2="1270" stroke="#a3e635" stroke-width="1.5" marker-end="url(#a-sub)"/>
<line x1="317" y1="1080" x2="317" y2="1240" stroke="#a3e635" stroke-width="1.5"/>
<line x1="317" y1="1240" x2="712" y2="1240" stroke="#a3e635" stroke-width="1.5"/>
<line x1="712" y1="1240" x2="712" y2="1270" stroke="#a3e635" stroke-width="1.5" marker-end="url(#a-sub)"/>
<line x1="332" y1="1080" x2="332" y2="1236" stroke="#a3e635" stroke-width="1.5"/>
<line x1="332" y1="1236" x2="912" y2="1236" stroke="#a3e635" stroke-width="1.5"/>
<line x1="912" y1="1236" x2="912" y2="1270" stroke="#a3e635" stroke-width="1.5" marker-end="url(#a-sub)"/>

<!-- Rubyx → Shopping -->
<line x1="912" y1="1080" x2="912" y2="1400" stroke="#f97316" stroke-width="1.5" marker-end="url(#a-exp)"/>

<!-- SBI Lifestyle → Shopping -->
<line x1="1512" y1="1080" x2="1512" y2="1376" stroke="#f97316" stroke-width="1.5"/>
<line x1="1512" y1="1376" x2="1312" y2="1376" stroke="#f97316" stroke-width="1.5"/>
<line x1="1312" y1="1376" x2="1312" y2="1400" stroke="#f97316" stroke-width="1.5" marker-end="url(#a-exp)"/>
</svg>`;

export default function FundFlowMap() {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <div className={styles.sectionTitle}>Fund Flow</div>
        <div className={styles.sectionMeta}>Full money map · v13</div>
      </div>

      <div className={styles.legend}>
        {LEGEND.map(({ color, label }) => (
          <div key={label} className={styles.legendItem}>
            <div className={styles.legendDot} style={{ background: color }} />
            {label}
          </div>
        ))}
      </div>

      <div
        className={styles.canvasWrap}
        dangerouslySetInnerHTML={{ __html: MAP_SVG }}
      />
    </section>
  );
}
