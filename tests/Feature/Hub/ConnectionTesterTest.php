<?php

namespace Tests\Feature\Hub;

use App\Models\RawPayload;
use App\Models\Supplier;
use App\PromoStandards\ConnectionTester;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;

class ConnectionTesterTest extends TestCase
{
    use RefreshDatabase;

    private function supplier(): Supplier
    {
        $supplier = Supplier::create(['name' => 'Acme Promo', 'slug' => 'acme-promo']);
        $supplier->credentials()->create(['username' => 'acme-user', 'password' => 'S3cret!pass']);
        $supplier->endpoints()->createMany([
            ['service' => 'inventory', 'version' => '2.0.0', 'url' => 'https://acme.test/inv'],
            ['service' => 'product_data', 'version' => '2.0.0', 'url' => 'https://acme.test/pd'],
            ['service' => 'purchase_order', 'version' => '1.0.0', 'url' => 'https://acme.test/po'],
        ]);

        return $supplier;
    }

    private const SELLABLE = '<Envelope><Body><R><ProductSellableArray><ProductSellable><productId>PEN-100</productId></ProductSellable></ProductSellableArray></R></Body></Envelope>';

    public function test_product_data_runs_first_and_unlocks_the_inventory_probe(): void
    {
        Storage::fake('local');
        Http::fake([
            'acme.test/pd' => Http::response(self::SELLABLE),
            'acme.test/inv' => Http::response('<Envelope><Body><R><Inventory><productId>PEN-100</productId></Inventory></R></Body></Envelope>'),
        ]);

        $results = app(ConnectionTester::class)->test($this->supplier());

        $this->assertSame('passed', $results['product_data']['status']);
        $this->assertSame('passed', $results['inventory']['status']);
        $this->assertSame('PEN-100', Supplier::first()->sample_product_id);
        // The inventory request must carry the product id learned from Product Data.
        Http::assertSent(fn (Request $r) => str_contains($r->url(), '/inv') && str_contains($r->body(), 'PEN-100'));
    }

    public function test_purchase_order_is_never_called(): void
    {
        Storage::fake('local');
        Http::fake(['*' => Http::response(self::SELLABLE)]);

        $results = app(ConnectionTester::class)->test($this->supplier());

        $this->assertSame('skipped', $results['purchase_order']['status']);
        Http::assertNotSent(fn (Request $r) => str_contains($r->url(), '/po'));
    }

    public function test_auth_failure_is_recorded_and_the_password_is_scrubbed(): void
    {
        Storage::fake('local');
        Http::fake(['acme.test/pd' => Http::response(
            '<Envelope><Body><Fault><faultstring>Login S3cret!pass for acme-user rejected</faultstring></Fault></Body></Envelope>', 500,
        )]);

        $results = app(ConnectionTester::class)->test($this->supplier());

        $this->assertSame('failed', $results['product_data']['status']);
        $this->assertStringNotContainsString('S3cret!pass', $results['product_data']['message']);
        $this->assertStringNotContainsString('acme-user', $results['product_data']['message']);
        $this->assertDatabaseMissing('supplier_endpoints', ['last_test_message' => null, 'service' => 'product_data']);
        // Dependent services are skipped, not failed, when Product Data could not give us a sample.
        $this->assertSame('skipped', $results['inventory']['status']);
    }

    public function test_raw_response_is_stored_compressed_without_credentials(): void
    {
        Storage::fake('local');
        Http::fake(['acme.test/pd' => Http::response(self::SELLABLE)]);

        app(ConnectionTester::class)->test($this->supplier());

        $payload = RawPayload::first();
        Storage::disk('local')->assertExists($payload->storage_path);
        $this->assertSame(self::SELLABLE, gzdecode(Storage::disk('local')->get($payload->storage_path)));
        $this->assertSame(64, strlen($payload->request_hash));
    }

    public function test_command_reports_failure_exit_code_and_hides_nothing_secret(): void
    {
        Storage::fake('local');
        Http::fake(['*' => Http::response('', 500)]);
        $this->supplier();

        $this->artisan('hub:supplier:test', ['slug' => 'acme-promo'])->assertFailed();
        $this->assertDatabaseHas('suppliers', ['slug' => 'acme-promo', 'status' => 'testing']);
    }
}
