<?php

namespace Tests\Feature\Hub;

use App\Models\Supplier;
use App\Models\SupplierEndpoint;
use App\PromoStandards\DirectoryImporter;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class DirectoryImporterTest extends TestCase
{
    use RefreshDatabase;

    // Fixture in the shape we EXPECT the directory to use; the real export is unverified.
    private const FIXTURE = '{"Companies":[
        {"Code":"ACME","Name":"Acme Promo","Services":[
            {"Type":"ProductData","Version":"2.0.0","URL":"https://acme.test/pd"},
            {"Type":"Inventory","Version":"2.0.0","URL":"https://acme.test/inv"},
            {"Type":"SomethingNew","Version":"1.0.0","URL":"https://acme.test/x"}]},
        {"Code":"BETA","Name":"Beta Goods","Services":[
            {"Type":"Media","Version":"1.1.0","URL":"https://beta.test/media"}]}]}';

    public function test_import_creates_supplier_and_maps_services(): void
    {
        $importer = new DirectoryImporter;
        $stats = $importer->import($importer->parseJson(self::FIXTURE), ['ACME']);

        $this->assertSame(1, $stats['suppliers']);
        $this->assertSame(2, $stats['endpoints']);
        $this->assertSame(['SomethingNew'], $stats['unmapped']);
        $this->assertDatabaseHas('supplier_endpoints', ['service' => 'product_data', 'url' => 'https://acme.test/pd']);
        $this->assertDatabaseMissing('suppliers', ['promostandards_code' => 'BETA']);
    }

    public function test_reimport_is_idempotent_and_updates_urls(): void
    {
        $importer = new DirectoryImporter;
        $records = $importer->parseJson(self::FIXTURE);
        $importer->import($records, ['ACME']);
        $records[0]['services'][0]['url'] = 'https://acme.test/pd-v2';
        $importer->import($records, ['ACME']);

        $this->assertSame(1, Supplier::count());
        $this->assertSame(2, SupplierEndpoint::count());
        $this->assertDatabaseHas('supplier_endpoints', ['url' => 'https://acme.test/pd-v2']);
    }

    public function test_manual_endpoints_survive_a_reimport(): void
    {
        $importer = new DirectoryImporter;
        $records = $importer->parseJson(self::FIXTURE);
        $importer->import($records, ['ACME']);
        SupplierEndpoint::where('service', 'inventory')->update(['url' => 'https://override.test/inv', 'source' => 'manual']);

        $stats = $importer->import($records, ['ACME']);

        $this->assertSame(1, $stats['skipped_manual']);
        $this->assertDatabaseHas('supplier_endpoints', ['url' => 'https://override.test/inv']);
    }

    public function test_whole_directory_import_stays_inactive(): void
    {
        $importer = new DirectoryImporter;
        $importer->import($importer->parseJson(self::FIXTURE), null, activate: false);

        $this->assertSame(2, Supplier::count());
        $this->assertSame(0, Supplier::active()->count());
    }

    public function test_command_refuses_to_run_without_a_selection(): void
    {
        $this->artisan('hub:directory:import', ['--file' => __FILE__])->assertFailed();
    }
}
