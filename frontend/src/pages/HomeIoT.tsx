import DomainPage from '../components/DomainPage';
import { domains } from '../data/mockData';

export default function HomeIoT() {
  return <DomainPage domain={domains.home} />;
}
