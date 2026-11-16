import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MoatPanel, MoatClassificationPanel, MoatChecklistPanel } from '@/components/research/MoatPanel';
import type { MoatScoreMetric, ResearchMoat } from '@/lib/actions/research.actions';
import { createTranslator } from '@/lib/i18n/translate';
import { createFormatters } from '@/lib/format';
const ti=createTranslator('en');const fmt=createFormatters('en');
const mature={company_type:'mature',sector:'Technology',factor_tags:[] as string[],valuation_model:'dcf'};
const metric=(trace:object={},status='ok')=>({status,calculation_trace:trace,definition_version:'fixture-v2'} as MoatScoreMetric);
const check=(id:string,metric:string,value:string|null,threshold:string|null,passed:boolean|null)=>({check:id,metric,value,threshold,passed});
describe('moat financial checks require comparable evidence',()=>{
    it('counts only evaluable checks and separately marks pass/fail/no data with their thresholds',()=>{
        const checks=[check('fcf_margin_5y_gt_5pct','fcf_margin_5y','0.08','0.05',true),check('roic_gt_wacc','roic','0.04','0.09',false),check('cfroi_approx_gt_wacc','cfroi_approx',null,null,null),check('owner_earnings_5y_positive','owner_earnings_5y','1500000',null,true),check('capex_to_da_5y_le_150pct','capex_to_da_5y','1.1',null,true),check('future_check','future_metric','3',null,true)];
        render(<MoatPanel metric={metric({checks},'partial')} company={mature} ti={ti} fmt={fmt}/>);
        expect(screen.getByText('4/5')).toBeInTheDocument();expect(screen.getByText(/> WACC.*9/)).toBeInTheDocument();expect(screen.getByText('> WACC')).toBeInTheDocument();expect(screen.getByText('≤ 1.5')).toBeInTheDocument();expect(screen.getByText('> 0')).toBeInTheDocument();expect(screen.getByText('future_check')).toBeInTheDocument();expect(screen.getAllByLabelText(/passed|not assessable/i).length).toBeGreaterThan(0);
    });
    it('does not turn unavailable or empty history into a perfect score',()=>{const ui=render(<MoatPanel metric={metric({},'unavailable')} company={mature} ti={ti}/>);expect(screen.queryByRole('list')).not.toBeInTheDocument();ui.rerender(<MoatPanel metric={metric({checks:[]})} company={mature} ti={ti}/>);expect(screen.queryByText('0/0')).not.toBeInTheDocument();});
    it.each([
        {company_type:'pre_fcf_telecom',factor_tags:['telecom']},
        {company_type:'pre_revenue'}, {factor_tags:['pre_fcf']},
        {company_type:'bank'}, {company_type:'insurer'}, {sector:'Financials'},
        {company_type:'mining'}, {factor_tags:['commodities']}, {factor_tags:['cyclical']},
        {company_type:'growth'}, {factor_tags:['growth']}, {factor_tags:['speculative']}, {valuation_model:'speculative'},
        {company_type:'unknown'}, {valuation_model:'unassigned'},
    ])('does not reuse a mature historical score for incompatible profile %j',patch=>{
        render(<MoatPanel metric={metric({profile:'mature',score:8,checks_total:8,checks_evaluable:8})} company={{...mature,...patch}} ti={ti}/>);expect(screen.queryByText('8/8')).not.toBeInTheDocument();expect(screen.queryByRole('list')).not.toBeInTheDocument();expect(screen.getByText(/Not assessable with the 8 general thresholds/)).toBeInTheDocument();
    });
    it('uses a matching profile reason, but not a stale reason from another profile',()=>{const ui=render(<MoatPanel metric={metric({profile:'early_stage',profile_reason:'Fixture specific reason'})} company={{...mature,company_type:'pre_fcf'}} ti={ti}/>);expect(screen.getByText(/Fixture specific reason/)).toBeInTheDocument();ui.rerender(<MoatPanel metric={metric({profile:'mature',profile_reason:'Wrong profile reason'})} company={{...mature,company_type:'bank'}} ti={ti}/>);expect(screen.queryByText(/Wrong profile reason/)).not.toBeInTheDocument();});
    it('honors backend non-comparability even for mature company metadata',()=>{render(<MoatPanel metric={metric({score_comparable:false,profile:'mature',profile_reason:'Backend exclusion'})} company={mature} ti={ti}/>);expect(screen.getByText(/Backend exclusion/)).toBeInTheDocument();expect(screen.queryByRole('list')).not.toBeInTheDocument();});
    it('uses the explicit backend counts and threshold when provided',()=>{render(<MoatPanel metric={metric({score:1,checks_total:1,checks_evaluable:1,profile_label:'Fixture mature',checks:[check('capex_to_da_5y_le_150pct','capex_to_da_5y','1.1','1.2',true)]})} company={mature} ti={ti} fmt={fmt}/>);expect(screen.getByText('1/1')).toBeInTheDocument();expect(screen.getByText('≤ 1.2')).toBeInTheDocument();expect(screen.getByText(/Fixture mature/)).toBeInTheDocument();});
});
describe('qualitative moat evidence is not a numeric verdict',()=>{
    const moat:ResearchMoat={ticker:'TEST',status:'ok',methodology:'fixture',moats:[],nico_mapping:{version:'test',types:{network:'Network fixture',scale:'Scale fixture'},mapping:{network_effect:'network'},unclassified:['future_type']},qualitative_checklist:[]};
    it('omits absent classification/checklist instead of making up categories',()=>{const ui=render(<><MoatClassificationPanel moat={null}/><MoatChecklistPanel moat={null}/></>);expect(ui.container).toBeEmptyDOMElement();});
    it('counts classified evidence without treating unmapped evidence as absent',()=>{render(<MoatClassificationPanel moat={{...moat,moats:[{type:'network_effect',nico_classification:{type:'network',label:'Network',method:'fixture',basis:'fixture'},strength:1,trend:'stable',persistence:'unknown',confidence:1,status:'ok',supporting_claim_ids:[],contradicting_claim_ids:[]}]}} ti={ti} locale="en"/>);expect(screen.getByRole('heading',{name:'Network fixture'})).toBeInTheDocument();expect(screen.getByText(/1 category assessed/i)).toBeInTheDocument();expect(screen.getByText(/0 categories assessed/i)).toBeInTheDocument();expect(screen.getByText(/Unclassified/,{selector:"li"})).toBeInTheDocument();});
    it('keeps supporting, contradicting and unclassified citations distinct and exposes missing evidence',()=>{render(<MoatChecklistPanel moat={{...moat,qualitative_checklist:[{id:'empty',question:'Missing fixture',status:'unknown',excerpts:[]},{id:'evidence',question:'Evidence fixture',status:'partial',excerpts:['supports','contradicts','other'].map((relation,i)=>({quote:`Quote ${i}`,source_title:`Source ${i}`,source_url:`https://example.com/${i}`,published_at:null,relation}))}]}} ti={ti}/>);expect(screen.getByText('Missing fixture')).toBeInTheDocument();expect(screen.getAllByRole('link')).toHaveLength(3);expect(screen.getByRole('link',{name:'Source 1'})).toHaveAttribute('href','https://example.com/1');expect(screen.getByText(/against/i)).toBeInTheDocument();expect(screen.getByText(/Evidence for/i)).toBeInTheDocument();});
});
