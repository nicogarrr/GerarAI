import { describe, expect, it } from 'vitest';
import { frameworkTerm } from '@/lib/research/framework-terms';
import es from '@/lib/i18n/messages/es/researchShared.json';
import en from '@/lib/i18n/messages/en/researchShared.json';

const terms = ['auto_energy_optionality', 'vehicle_deliveries', 'average_selling_price',
    'energy_storage_deployed', 'energy_storage_price', 'fsd_attach_rate', 'robotaxi_vehicles',
    'robotaxi_revenue_per_vehicle', 'optimus_units', 'optimus_price', 'automotive_gross_margin', 'deliveries', 'storage', 'optionality',
    'attach_rate', 'automotive', 'energy', 'fsd_robotaxi', 'optimus', 'demand', 'battery_supply', 'autonomy_regulation'];
const camel = (key: string) => key.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());

describe('auto/energy framework terms use the shared messages', () => {
    for (const term of terms) {
        it(`${term} resolves in Spanish and English`, () => {
            const key = camel(term) as keyof typeof es.frameworkTerms.autoEnergy;
            expect(frameworkTerm(term, 'es')).toBe(es.frameworkTerms.autoEnergy[key]);
            expect(frameworkTerm(term, 'en')).toBe(en.frameworkTerms.autoEnergy[key]);
        });
    }
    it('translates formulas term by term', () => {
        expect(frameworkTerm('vehicle_deliveries × average_selling_price', 'es'))
            .toBe('entregas de vehículos × precio medio de venta');
        expect(frameworkTerm('vehicle_deliveries × average_selling_price', 'en'))
            .toBe('vehicle deliveries × average selling price');
    });
});
