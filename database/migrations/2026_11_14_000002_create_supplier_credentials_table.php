<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('supplier_credentials', function (Blueprint $table) {
            $table->id();
            $table->foreignId('supplier_id')->unique()->constrained()->cascadeOnDelete();
            // Both columns hold Laravel-encrypted ciphertext (see SupplierCredential casts),
            // so they are TEXT: ciphertext is much longer than the plain value.
            $table->text('username');
            $table->text('password');
            $table->timestamp('rotated_at')->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('supplier_credentials');
    }
};
