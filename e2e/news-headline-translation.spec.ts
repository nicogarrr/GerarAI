import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

// Disposable fixture with a mocked translation endpoint; no live LLM call.
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

for (const width of [390,820,1440]) test(`translated headline preserves original ${width}`, async ({page,request}) => {
 const marker=randomUUID().slice(0,8);
 const original=`Microsoft कंपनी ने परिणाम 2026 घोषित किए ${marker}`;
 await post(request,"/api/news/ingest",{source:"manual_feed",items:[{ticker:"MSFT",title:original,text:original,url:`https://example.com/${marker}`} ]});
 let calls=0;
 const rows=await request.get(`${apiBase}/api/news`,{headers:signedHeaders("GET","/api/news",Buffer.alloc(0))});
 const own=(await rows.json()).find((r:{url:string})=>r.url===`https://example.com/${marker}`);
 await page.route("**/api/news/*/translation",async route=>{
  if(route.request().url().endsWith(`/api/news/${own.id}/translation`)){calls++;await route.fulfill({json:{status:"translated",text:`La empresa anuncia resultados 2026 ${marker}`,original,target_language:"es",machine_translation:true}});}
  else await route.fulfill({json:{status:"unavailable"}});
 });
 await page.setViewportSize({width,height:1000});await page.goto("/research/news?lane=empresa");
 await page.addStyleTag({content:"nextjs-portal{display:none!important}"});
 const surface=width<768?page.getByRole("list",{name:"Eventos de noticias",exact:true}):page.getByRole("region",{name:"Flujo de eventos de noticias",exact:true});
 await expect(surface.getByText(`La empresa anuncia resultados 2026 ${marker}`,{exact:true})).toBeVisible();
 await expect(surface.getByText("Traducción automática · español").first()).toBeVisible();
 await surface.getByText("Ver original").first().click();
 await expect(surface.getByText(original,{exact:true})).toBeVisible();
 expect(calls).toBe(1);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:`test-results/news-translation-${width}.png`});
});
