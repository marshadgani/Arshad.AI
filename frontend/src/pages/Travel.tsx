import DomainPage from '../components/DomainPage';
import { domains } from '../data/mockData';

export default function Travel() {
  return <DomainPage domain={domains.travel} />;
}
