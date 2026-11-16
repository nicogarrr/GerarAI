import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LongTermModelPanel, ownerEarningsFormulaLabel, termLabel } from '@/components/research/FundamentalModelPanels';
import { MODELO_SIN_VALORACION as fixture } from './fixtures/long-term-model-sin-valoracion';
import { createTranslator } from '@/lib/i18n/translate';
import { LocaleProvider } from '@/lib/i18n/client';
import type { ResearchLongTermModel } from '@/lib/actions/research.actions';
vi.mock('@/components/GlossaryTerm',()=>({GlossaryTerm:({children}:{children:React.ReactNode})=><span>{children}</span>}));
vi.mock('@/components/research/ScenarioAssumptions',()=>({default:()=>null}));
const t=createTranslator('en');
const panel=(model:ResearchLongTermModel,ticker?:string)=><LocaleProvider locale="en"><LongTermModelPanel model={model} ticker={ticker} t={t} locale="en"/></LocaleProvider>;
const clone=()=>structuredClone(fixture);
describe('fundamental model conditions require identifiable source data',()=>{
    it('shows explicit model conditions rather than accepting backend prose as proof they were met',()=>{
        const model=clone();model.what_must_be_true=['revenue_growth','fcf_margin','roic_above_wacc','price_expectations','share_count','competitive_position','binding_constraint','future_condition'].map(id=>({id,unit:'ratio',source_fact_ids:[],condition:id==='future_condition'?'Future condition must stay visible':'Backend placeholder',value:0.08,comparison:0.04,status:'ok'}));
        model.market_opportunity.constraints.binding_constraint='revenue';model.assumptions.wacc.source_type='model_policy';
        render(panel(model,'BRK/B'));expect(screen.getByText('Future condition must stay visible')).toBeInTheDocument();expect(screen.queryByText('Backend placeholder')).not.toBeInTheDocument();expect(screen.getByRole('link')).toHaveAttribute('href','/research/BRK%2FB?view=valuation');expect(screen.getAllByText(/WACC.*source|WACC.*sourc/i).length).toBeGreaterThan(0);
    });
    it('keeps missing condition values and binding constraints explicit',()=>{
        const model=clone();model.what_must_be_true=['revenue_growth','fcf_margin','roic_above_wacc','price_expectations','binding_constraint'].map(id=>({id,unit:'ratio',source_fact_ids:[],condition:'placeholder',value:null,comparison:null,status:'blocked'})); model.scenarios={};model.assumptions={};model.as_of_period=null;
        render(panel(model));expect(screen.getAllByText(/N\/A/).length).toBeGreaterThan(0);expect(screen.queryByText('NaN')).not.toBeInTheDocument();expect(screen.queryByText(/Infinity/)).not.toBeInTheDocument();
    });
    it('shows source references with safe labels and distinguishes traceable assumptions from empty sources',()=>{
        const model=clone();model.assumptions.revenue_growth.fuentes=[{fact_id:7,titulo:'Annual filing',url:'https://example.com/annual',fecha:'2025-12-31'},{fact_id:8,titulo:null,url:null,fecha:null}];model.assumptions.fcf_margin.fuentes=[{fact_id:9,titulo:null,url:'https://example.com/fact',fecha:null}];model.owner_earnings={...model.owner_earnings,status:'ok',value:123456,formula:'net income + D&A - maintenance capex - normalized change in working capital'};model.quality_of_growth.conclusion='Fixture growth caveat';model.timeline=[{date:'2026-11-15T10:00:00Z',title:'Dated fixture',type:'earnings',source:'Fixture filing',thesis_impact:'positive'},{date:null,title:'Undated fixture',type:'future',source:'Fixture filing',thesis_impact:'future'}];
        render(panel(model));expect(screen.getByRole('link',{name:/Annual filing/})).toHaveAttribute('href','https://example.com/annual');expect(screen.getByRole('link',{name:/official/i})).toHaveAttribute('href','https://example.com/fact');expect(screen.getByText('Fixture growth caveat')).toBeInTheDocument();expect(screen.getByText('Undated fixture')).toBeInTheDocument();expect(screen.getByText(/net income.*maintenance capex/)).toBeInTheDocument();
    });
    it('does not expose scenario values for a non-publishable model even if the backend supplied them',()=>{
        const model=clone();model.publishable=false;model.status='preview_only';model.missing_inputs=['wacc'];model.scenarios.base.valuation={value_per_share:987654} as typeof model.scenarios.base.valuation;render(panel(model));expect(screen.queryByRole('table')).not.toBeInTheDocument();expect(screen.queryByText(/987/)).not.toBeInTheDocument();expect(screen.getAllByText(/not publish|publishable/i).length).toBeGreaterThan(0);
    });
    it('shows valid scenario values, sourced WACC, reverse assumptions and actual historical year when supported',()=>{
        const model=clone();model.scenarios.base.valuation={value_per_share:123} as typeof model.scenarios.base.valuation;model.scenarios.base.year_5={...model.scenarios.base.terminal_year!,fcf_per_share:7};model.reverse_dcf={...model.reverse_dcf,status:'ok',required_revenue_growth:0.05,base_revenue_growth:0.04,fcf_margin:0.1};model.historical_review.years_covered=1;model.historical_review.first_year=null;model.historical_review.last_year=null;model.market_opportunity.verdict={...model.market_opportunity.verdict,label:'reasonable',conclusion:'Base revenue uses 50%',base_revenue_to_binding_capacity:0.5};model.market_opportunity.constraints.binding_constraint='revenue';model.quality_of_growth.quality='high';render(panel(model));expect(screen.getByRole('table')).toBeInTheDocument();expect(screen.getAllByText('123').length).toBeGreaterThan(0);expect(screen.getByText(/50.*%/)).toBeInTheDocument();expect(screen.getByText(/requires.*5|5.*%.*base/i)).toBeInTheDocument();
    });
    it('preserves unknown labels and formulas rather than dropping them',()=>{expect(ownerEarningsFormulaLabel('Future formula','es')).toBe('Future formula');expect(ownerEarningsFormulaLabel('net income + D&A - maintenance capex - normalized change in working capital')).toMatch(/beneficio neto/);expect(termLabel('future_driver','en')).toBeTruthy();});
});
