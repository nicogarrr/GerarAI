import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

// Quick win UX 5: badges «En cartera / En watchlist» en eventos de noticias.
// Semilla firmada (patrón f339, tenant del bypass de navegador): una
// posición COST, NFLX en watchlist y un evento de cada uno.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user";
const apiBase = E2E_UI_BACKEND_URL;

function signedHeaders(method: string, path: string, body: Buffer) {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", apiSecret)
    .update(`${apiUser}:${apiUser}:${timestamp}:${nonce}:${method}:${path}:${bodyHash}`)
    .digest("hex");
  return {
    "X-CavaAI-Tenant": apiUser,
    "X-CavaAI-User": apiUser,
    "X-CavaAI-Timestamp": timestamp,
    "X-CavaAI-Nonce": nonce,
    "X-CavaAI-Method": method,
    "X-CavaAI-Path": path,
    "X-CavaAI-Body-Hash": bodyHash,
    "X-CavaAI-Signature": signature,
    "Content-Type": "application/json",
  };
}

async function post(request: import("@playwright/test").APIRequestContext, path: string, payload: unknown) {
  const body = Buffer.from(JSON.stringify(payload));
  const res = await request.post(`${apiBase}${path}`, { data: body, headers: signedHeaders("POST", path, body) });
  expect(res.status(), await res.text()).toBeLessThan(300);
}

// La portada agrupa titulares de la misma historia (news_story_cluster.py,
// Jaccard/contencion en 48 h): 25 titulares casi identicos colapsan en uno.
// Cada item lleva dos palabras distintivas propias para ser historias distintas.
const WORDS_A = ["granite","harbour","lantern","meadow","orchard","pelican","quarry","ribbon","saddles","thicket","uplands","verdant","willows","yachting","zeppelin","amethyst","bramble","cobalt","dolphin","emerald","falcons","gargoyle","hamlets","iceberg","juniper"];
const WORDS_B = ["kestrels","limpets","mustang","nutmegs","ospreys","pumice","quokkas","rapids","sparrow","tundras","urchins","vellum","walnuts","xylitol","yarrows","zinnias","abalone","badgers","cormorant","dragonfly","eclipses","foxglove","glaciers","herons","ironwood"];

for(const width of [390,820,1440]) test(`news pages replace rather than append ${width}`,async({page,request})=>{
 const marker=randomUUID().slice(0,8);
 await post(request,"/api/news/ingest",{source:"manual_feed",items:Array.from({length:25},(_,i)=>({ticker:"MSFT",title:`Microsoft ${WORDS_A[i]} ${WORDS_B[i]} ${marker}`,text:"Microsoft announced a product.",url:`https://example.com/${marker}/${i}`}))});
 await page.setViewportSize({width,height:1000});await page.goto("/research/news?lane=empresa");
 await page.addStyleTag({content:"nextjs-portal{display:none!important}"});
 const pager=page.getByRole("navigation",{name:"Paginación",exact:true});
 await expect(pager.getByText("Página 1",{exact:true})).toBeVisible();
 const first=await page.locator("main li").allTextContents();
 await expect(pager.getByRole("link",{name:"Siguiente"})).toBeInViewport();
 await page.screenshot({path:`test-results/news-pager-${width}.png`});
 await pager.getByRole("link",{name:"Siguiente"}).click();
 await expect(page).toHaveURL(/lane=empresa.*pagina=2/);
 await expect(pager.getByText("Página 2",{exact:true})).toBeVisible();
 const second=await page.locator("main li").allTextContents();
 expect(first.length).toBe(10);expect(second.length).toBe(10);
 expect(second.some(s=>first.includes(s))).toBe(false);
 await page.getByRole("navigation",{name:"Filtrar por carril"}).getByRole("link",{name:"Macro",exact:true}).click();
 await expect(page).toHaveURL(/lane=macro$/);
 await expect(pager.getByText("Página 1",{exact:true})).toBeVisible();
});
