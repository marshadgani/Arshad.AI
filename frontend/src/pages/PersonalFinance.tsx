import { BrokerageHoldings } from '../components/finance';
import DomainPage from '../components/DomainPage';
import FundFlowMap from '../components/FundFlowMap';

export default function PersonalFinance() {
  return (
    <DomainPage slug="finance">
      <FundFlowMap />
      <BrokerageHoldings />
    </DomainPage>
  );
}
